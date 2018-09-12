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
    _destroy_index, init_es
)


class Command(BaseCommand):
    help = 'Index documents'

    def add_arguments(self, parser):
        parser.add_argument('path', type=str)
        parser.add_argument("-r", action='store_true',
                            dest='reindex')

    def handle(self, *args, **options):
        if options['reindex']:
            print('Reindexing: destroying index!')
            _destroy_index()
            init_es()

        names = glob.glob(
            os.path.join(options['path'], '**/**/*.pdf')
        )
        names = list(sorted(n for n in names if '_original' not in n))

        with Pool(4) as pool:
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
    text = None
    for entry in pub.entries.all():

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

        if text is None:
            text = list(get_text(filename))

        start = 0
        if entry.pdf_page is not None:
            start = entry.pdf_page - 1

        end = len(text)
        if entry.num_pages:
            end = start + entry.num_pages + 1

        p.content = list(text[start:end])

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
