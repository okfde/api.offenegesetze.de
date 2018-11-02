from glob import glob
import os

from django.core.management.base import BaseCommand

from bgbl.importer import remove_watermark


class Command(BaseCommand):
    help = 'Remove watermark from pdfs'

    def add_arguments(self, parser):
        parser.add_argument('doc_path', type=str)

    def handle(self, *args, **options):
        doc_path = options['doc_path']
        if doc_path.endswith('.pdf'):
            filenames = [doc_path]
        else:
            filenames = glob(os.path.join(doc_path, '**/*.pdf'))

        for filename in filenames:
            if filename.endswith(('_original.pdf', '_watermarked.pdf')):
                continue
            watermarked_filename = filename.replace('.pdf', '_watermarked.pdf')
            if os.path.exists(watermarked_filename):
                continue
            remove_watermark(filename)
