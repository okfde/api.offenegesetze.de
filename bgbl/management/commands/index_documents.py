import glob
import os

from django.core.management.base import BaseCommand

from PyPDF2 import PdfFileReader
try:
    import pdflib
except ImportError:
    pdflib = None

from bgbl.models import Publication
from bgbl.es_models import Publication as ESPublication


class Command(BaseCommand):
    help = 'Index documents'

    def add_arguments(self, parser):
        parser.add_argument('path', type=str)

    def handle(self, *args, **options):
        names = glob.glob(os.path.join(options['path'], '*.pdf'))
        for filename in names:
            self.load_name(filename)

    def load_name(self, filename):
        print(filename)
        # documents_1_1970_25_unlocked_ocr.pdf
        parts = os.path.basename(filename).split('_')
        kind = parts[1]
        year = parts[2]
        number = parts[3]
        print(kind, year, number)
        pub = Publication.objects.get(
            kind='bgbl%s' % kind,
            year=int(year),
            number=int(number)
        )

        text = '\n'.join(self.get_text(filename))

        # instantiate the document
        pub_id = '%s-%s-%s' % (
            pub.kind,
            pub.year,
            pub.number,
        )

        try:
            pub = ESPublication.get(
                id=pub_id,
            )
        except Exception:
            pub = ESPublication(
                id=pub_id,
                kind=pub.kind,
                year=pub.year,
                number=pub.number,
            )
        pub.date = pub.date
        pub.page = pub.page
        pub.content = text
        pub.save()

    def get_text(self, filename):
        pdf_reader = PdfFileReader(filename)
        num_pages = pdf_reader.getNumPages()
        pages = range(num_pages)

        pdflib_pages = None
        if pdflib is not None:
            pdflib_doc = pdflib.Document(filename)
            pdflib_pages = list(pdflib_doc)
        for page_no in pages:
            if pdflib_pages is not None:
                page = pdflib_pages[page_no]
                text = ' '.join(page.lines).strip()
            else:
                page = pdf_reader.getPage(page_no)
                text = page.extractText()
            yield text.strip()
