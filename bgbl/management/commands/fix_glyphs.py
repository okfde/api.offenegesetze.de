from glob import glob
import os
import shutil

from django.core.management.base import BaseCommand

from bgbl.pdf_utils import fix_glyphs, remove_watermark


class Command(BaseCommand):
    help = 'Fix glyphs pdfs'

    def add_arguments(self, parser):
        parser.add_argument('doc_path', type=str)

    def handle(self, *args, **options):
        doc_path = options['doc_path']
        if doc_path.endswith('.pdf'):
            filenames = [doc_path]
        else:
            pattern = os.path.join(doc_path, '**/*.pdf')
            filenames = glob(pattern, recursive=True)

        for original_filename in filenames:
            if filename.endswith(('_original.pdf', '_watermarked.pdf')):
                continue

            print('Fix glyphs', original_filename)
            fixed_filename = fix_glyphs(original_filename)
            real_filename = fixed_filename.replace('_fixed.pdf', '.pdf')

            if os.path.exists(real_filename):
                os.remove(real_filename)
            shutil.move(fixed_filename, real_filename)

            print('Adding meta data', real_filename)
            remove_watermark(real_filename, force=True)
