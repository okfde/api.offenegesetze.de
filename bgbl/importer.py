from datetime import date
import itertools
import os

from PyPDF2 import PdfFileReader
try:
    import pdflib
except ImportError:
    pdflib = None

import dataset

import elasticsearch

from bgbl.models import Publication, PublicationEntry
from bgbl.search_indexes import (
    Publication as PublicationIndex,
)


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
    return zip(a, b)


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
                self.index_document(publication, entry)

        return created

    def index_document(self, pub, entry):
        pub_path = pub.get_path(self.document_path)
        if not os.path.exists(pub_path):
            print('File not found', pub_path)
            return False

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
            if not self.reindex:
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
                text = ' '.join(page.lines).strip()
            except UnicodeDecodeError:
                pass
        if text is None:
            page = pdf_reader.getPage(page_no)
            text = page.extractText()
        yield text.strip()
