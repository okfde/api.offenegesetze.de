from datetime import date
import itertools
import logging
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
from .pdf_utils import remove_watermark

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


def previous_and_next(some_iterable):
    prevs, items, nexts = itertools.tee(some_iterable, 3)
    prevs = itertools.chain([None], prevs)
    nexts = itertools.chain(itertools.islice(nexts, 1, None), [None])
    return zip(prevs, items, nexts)


def get_pub_key(entry):
    return (entry['part'], entry['year'], entry['number'])


class BGBlImporter:
    def __init__(self, db_path, document_path, rerun=False,
                 reindex=False, parts=None, watermark=False,
                 years=None, numbers=None):
        self.db_path = db_path
        db = dataset.connect('sqlite:///' + db_path)
        self.table = db['data']
        self.document_path = document_path
        self.rerun = rerun
        self.reindex = reindex
        self.watermark = watermark
        self.years = years
        self.numbers = numbers
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
            if self.years is not None and entry['year'] not in self.years:
                continue
            if (self.numbers is not None and
                    entry['number'] not in self.numbers):
                continue
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
            if not created and not self.rerun and not self.reindex:
                return

    def import_publication(self, part, year, number):
        entries = self.table.find(
            part=part, year=year,
            number=number, order_by=['order']
        )
        publication = None
        created = True
        last_pdf_page = None
        last_page = None

        for prev_entry, entry, next_entry in previous_and_next(entries):
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
                if self.watermark:
                    filename = publication.get_path(self.document_path)
                    remove_watermark(filename, publication=publication)

                if not created and not self.rerun and not self.reindex:
                    print('Skipping')
                    return False

                if self.rerun:
                    PublicationEntry.objects.filter(
                        publication=publication).delete()

            if entry['kind'] == 'meta':
                continue

            if last_page is not None and entry['page'] is not None:
                pdf_page = last_pdf_page + entry['page'] - last_page
            elif prev_entry is not None and (
                    prev_entry['page'] is not None and
                    entry['page'] is not None):
                # first non-meta entry always? starts on fresh page after meta
                pdf_page = entry['page'] - prev_entry['page'] + 1
            else:
                # best guess
                pdf_page = 2

            num_pages = 1
            if next_entry and (
                    next_entry['page'] is not None and
                    entry['page'] is not None):
                num_pages = max(next_entry['page'] - entry['page'], 1)
            elif next_entry is None:
                total_pages = get_num_pages(publication, self.document_path)
                num_pages = total_pages - pdf_page + 1

            if entry['page'] is not None:
                last_page = entry['page'] + num_pages - 1
            else:
                last_page = num_pages - 1
            last_pdf_page = pdf_page + num_pages - 1

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


def get_num_pages(pub, document_path):
    if hasattr(pub, 'num_pages'):
        return pub.num_pages
    filename = pub.get_path(document_path)
    pdf_reader = PdfFileReader(filename)
    pub.num_pages = pdf_reader.getNumPages()
    return pub.num_pages


def index_entry(pub, entry, document_path='', reindex=False):
    pub_path = pub.get_path(document_path)
    if not os.path.exists(pub_path):
        print('File not found', pub_path)
        return None

    pub_id = '%s-%s-%s-%s' % (
        pub.kind,
        pub.year,
        pub.number,
        entry.index_order
    )

    data = dict(
        kind=pub.kind,
        year=pub.year,
        number=pub.number,
        date=pub.date,
        order=entry.index_order,
        page=entry.page,
        pdf_page=entry.pdf_page,
        law_date=entry.law_date,
        num_pages=entry.num_pages,
        title=entry.title,
    )

    try:
        p = PublicationIndex.get(
            id=pub_id
        )
        if not reindex:
            # Already in index
            return
        # Update all properties
        for k, v in data.items():
            setattr(p, k, v)
    except elasticsearch.exceptions.NotFoundError:
        p = PublicationIndex(**data)
        p.meta.id = pub_id

    if not hasattr(pub, '_text'):
        pub._text = list(get_text(pub_path))

    start = 0
    if entry.pdf_page is not None:
        start = entry.pdf_page - 1

    end = len(pub._text)
    if entry.num_pages:
        end = start + entry.num_pages

    p.content = list(pub._text[start:end])

    TRIES = 5
    for i in range(TRIES):
        try:
            p.save(timeout='3m')
            return p
        except Exception as e:
            logger.exception()
            logger.warn('Could not save %s (try %s)', pub_id, i)
            if i == TRIES - 1:
                raise e


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
