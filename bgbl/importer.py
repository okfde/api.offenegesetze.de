from datetime import date
import itertools
from io import BytesIO
import logging
import os
import subprocess
import shutil
import tempfile

from PyPDF2 import PdfFileReader
try:
    import pdflib
except ImportError:
    pdflib = None

from pdfrw import PdfReader, PdfWriter, PdfDict, PdfName, PdfString

import dataset

import elasticsearch

from bgbl.models import Publication, PublicationEntry
from bgbl.search_indexes import (
    Publication as PublicationIndex,
)

logger = logging.getLogger(__name__)


FIX_LIST = {
    '14.40.2016': '14.04.2016',
    '31.09.1998': '31.08.1998',
    '09.6..06.0': '06.06.2009',
    '09.1..15.0': '15.01.2009',
    '09.3..13.0': '13.03.2009',
    '09.4..21.0': '21.04.2009',
    '08.20.0808': '08.08.2008',
    '09.24.1990': '24.09.1990',
    '30.02.2018': '30.05.2018',
}


def make_date(val):
    if val is None:
        return None

    val = FIX_LIST.get(val, val)
    try:
        return date(
            *[int(x) for x in val.split('.')][::-1]
        )
    except Exception as e:
        print(val)
        raise


def pairwise(iterable):
    "s -> (None,s0), (s0,s1), (s1, s2), ..."
    a, b = itertools.tee(iterable)
    next(b, None)
    return itertools.zip_longest(a, b)


def get_pub_key(entry):
    return (entry['part'], entry['year'], entry['number'])


class BGBlImporter:
    def __init__(self, db_path, document_path, rerun=False,
                 reindex=False, parts=None):
        self.db_path = db_path
        db = dataset.connect('sqlite:///' + db_path)
        self.table = db['data']
        self.document_path = document_path
        self.rerun = rerun
        self.reindex = reindex
        if parts is None:
            self.parts = (1, 2)
        else:
            self.parts = parts

    def run_import(self):
        for part in self.parts:
            self.import_part(part)

    def get_issue_params(self, part):
        entries = self.table.find(part=part, order_by=['-year', '-number'])
        current_pub_key = None
        for entry in entries:
            pub_key = get_pub_key(entry)
            if current_pub_key != pub_key:
                current_pub_key = pub_key
                yield pub_key

    def get_tasks(self):
        for part in self.parts:
            for pub_key in self.get_issue_params(part):
                yield (
                    self.db_path,
                    self.document_path,
                    {
                        'rerun': self.rerun,
                        'reindex': self.reindex,
                    },
                    pub_key
                )

    @classmethod
    def run_task(cls, args):
        imp = cls(args[0], args[1], **args[2])
        imp.import_publication(*args[3])

    def import_part(self, part):
        for pub_key in self.get_issue_params(part):
            print(pub_key)
            created = self.import_publication(*pub_key)
            if not created and not self.rerun:
                return

    def import_publication(self, part, year, number):
        entries = self.table.find(
            part=part, year=year,
            number=number, order_by=['order']
        )
        publication = None
        created = True
        page_offset = 0

        for entry, next_entry in pairwise(entries):
            if entry is None:
                continue

            if publication is None:
                publication, created = Publication.objects.get_or_create(
                    kind='bgbl%s' % entry['part'],
                    year=entry['year'],
                    number=entry['number'],
                    defaults={
                        'date': make_date(entry['date']),
                        'page': entry['page']
                    }
                )
                if not created and not self.rerun and not self.reindex:
                    print('Skipping')
                    return False

                if self.rerun:
                    PublicationEntry.objects.filter(
                        publication=publication).delete()

            if entry['kind'] == 'meta':
                if entry['page'] is not None:
                    # Set offset for these entries to
                    # the meta page (usually ToC)
                    page_offset = entry['page'] - 1
                continue

            pdf_page = (
                entry['page'] - page_offset
                if entry['page'] is not None else None
            )
            num_pages = 1
            if next_entry and next_entry['page'] and pdf_page is not None:
                next_pdf_page = next_entry['page'] - page_offset
                num_pages = next_pdf_page - pdf_page

            entry, entry_created = PublicationEntry.objects.get_or_create(
                publication=publication,
                order=entry['order'],
                defaults=dict(
                    title=entry['name'],
                    law_date=make_date(entry['law_date']),
                    page=entry['page'],
                    num_pages=num_pages,
                    pdf_page=pdf_page
                )
            )
            if entry_created or self.reindex:
                index_entry(
                    publication, entry,
                    document_path=self.document_path,
                    reindex=self.reindex
                )

        return created


def index_entry(pub, entry, document_path='', reindex=False):
    pub_path = pub.get_path(document_path)
    if not os.path.exists(pub_path):
        print('File not found', pub_path)
        return None

    pub_id = '%s-%s-%s-%s' % (
        pub.kind,
        pub.year,
        pub.number,
        entry.order
    )

    try:
        p = PublicationIndex.get(
            id=pub_id
        )
        if not reindex:
            # Already in index
            return
    except elasticsearch.exceptions.NotFoundError:
        p = PublicationIndex(
            kind=pub.kind,
            year=pub.year,
            number=pub.number,
            date=pub.date,
            order=entry.order,
            page=entry.page,
            pdf_page=entry.pdf_page,
            law_date=entry.law_date,
            num_pages=entry.num_pages,
            title=entry.title,
        )
    p.meta.id = pub_id

    if not hasattr(pub, '_text'):
        pub._text = list(get_text(pub_path))

    start = 0
    if entry.pdf_page is not None:
        start = entry.pdf_page - 1

    end = len(pub._text)
    if entry.num_pages:
        end = start + entry.num_pages + 1

    p.content = list(pub._text[start:end])

    p.save()
    return p


def get_text(filename):
    pdf_reader = PdfFileReader(filename)
    num_pages = pdf_reader.getNumPages()
    pages = range(num_pages)

    pdflib_pages = None
    if pdflib is not None:
        pdflib_doc = pdflib.Document(filename)
        pdflib_pages = list(pdflib_doc)
    for page_no in pages:
        text = None
        if pdflib_pages is not None:
            page = pdflib_pages[page_no]
            try:
                text = '\n'.join(page.lines).strip()
            except UnicodeDecodeError:
                pass
        if text is None:
            page = pdf_reader.getPage(page_no)
            text = page.extractText()
        yield text.strip()


def uncompress_pdf(filename):
    logger.debug('Uncompress PDF file with qpdf %s', filename)
    result = subprocess.run([
        'qpdf', '--stream-data=uncompress', filename, '-'
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr)
        raise RuntimeError()
    return BytesIO(result.stdout)


def compress_pdf(pdf_bytes):
    logger.debug('Compress PDF file with qpdf')
    f = tempfile.NamedTemporaryFile(suffix='.pdf', delete=False)
    try:
        f.write(pdf_bytes.getvalue())
        f.close()

        result = subprocess.run([
            'qpdf', '--linearize',
            f.name,
            '-'
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if result.returncode != 0:
            print(result.stdout)
            print(result.stderr)
            raise RuntimeError()
        return BytesIO(result.stdout)
    finally:
        os.remove(f.name)


WATERMARK_LINE = (
    '\n(Das Bundesgesetzblatt im Internet: www.bundesgesetzblatt'
    '.de | Ein Service des Bundesanzeiger Verlag www.bundesanzei'
    'ger-verlag.de)Tj'
)


def remove_watermark(filename, backup=True):
    pdf_file = uncompress_pdf(filename)

    doc = PdfReader(pdf_file)
    meta = {
        'Creator': 'OffeneGesetze.de',
        'Keywords': 'Amtliches Werk nach §5 UrhG https://offenegesetze.de'
    }

    for key, val in meta.items():
        doc.Info[PdfName(key)] = PdfString.from_unicode(val)

    doc = strip_all_xobjects(doc)

    for page_no, page in enumerate(doc.pages, 1):
        stream = page.Contents.stream
        if WATERMARK_LINE not in stream:
            logger.warning('PDF does not contain Watermark line: %s page %s',
                           filename, page_no)
        stream = stream.replace(WATERMARK_LINE, '')

        page.Contents = PdfDict()
        page.Contents.stream = stream
        page.Contents.Length = len(page.Contents.stream)

    output = BytesIO()
    outdata = PdfWriter(output)
    outdata.trailer = doc
    outdata.write()
    compressed_output = compress_pdf(output)

    if backup:
        watermarked_path = filename.replace('.pdf', '_watermarked.pdf')
        shutil.move(filename, watermarked_path)

    with open(filename, 'wb') as f:
        f.write(compressed_output.getvalue())


def strip_all_xobjects(pdf):
    for i, page in enumerate(pdf.pages):
        if page.Resources.XObject is None:
            continue
        names = list(page.Resources.XObject)
        for name in names:
            del page.Resources.XObject[name]

    return pdf
