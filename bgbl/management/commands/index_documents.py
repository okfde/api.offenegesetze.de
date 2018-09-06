import glob
import os
from multiprocessing import Pool
from functools import partial

from django.core.management.base import BaseCommand

from PyPDF2 import PdfFileReader
try:
    import pdflib
except ImportError:
    pdflib = None


import elasticsearch

from bgbl.models import Publication
from bgbl.search_indexes import (
    Publication as PublicationIndex,
    PublicationEntry as PublicationEntryIndex
)


class Command(BaseCommand):
    help = 'Index documents'

    def add_arguments(self, parser):
        parser.add_argument('path', type=str)
        parser.add_argument("-r", action='store_true',
                            dest='reindex')

    def handle(self, *args, **options):
        names = glob.glob(
            os.path.join(options['path'], '**/**/*.pdf')
        )
        names = list(sorted(n for n in names if '_original' not in n))

        with Pool(5) as pool:
            pool.map(
                partial(load_filename, reindex=options['reindex']),
                names
            )


def load_filename(filename, reindex=False):
    print(filename)
    parts = os.path.basename(filename).split('_')
    kind = parts[0]
    year = parts[1]
    number = parts[2].split('.')[0]
    print(kind, year, number)
    pub = Publication.objects.get(
        kind=kind,
        year=int(year),
        number=int(number)
    )

    pub_id = '%s-%s-%s' % (
        pub.kind,
        pub.year,
        pub.number,
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
        )
    p.meta.id = pub_id
    p.date = pub.date
    p.page = pub.page

    text = list(get_text(filename))
    p.content = text

    p.entries = [
        PublicationEntryIndex(**{
            'title': e.title,
            'law_date': e.law_date,
            'page': e.page,
            'order': e.order
        }) for e in pub.entries.all()
    ]
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
