from multiprocessing import Pool

from django.core.management.base import BaseCommand

from bgbl.search_indexes import (
    _destroy_index, init_es
)
from bgbl.importer import BGBlImporter


class Command(BaseCommand):
    help = 'Index documents'

    def add_arguments(self, parser):
        parser.add_argument('db_path', type=str)
        parser.add_argument('doc_path', type=str)
        parser.add_argument("-r", action='store_true',
                            dest='rerun')
        parser.add_argument("-i", action='store_true',
                            dest='reindex')
        parser.add_argument("-D", action='store_true',
                            dest='destroy_index')
        parser.add_argument("-m", action='store_true',
                            dest='watermark')
        parser.add_argument("-p", action='store_true',
                            dest='parallel')

    def handle(self, *args, **options):
        if options['destroy_index']:
            print('Destroying index!')
            try:
                _destroy_index()
            except Exception:
                pass
            init_es()

        imp = BGBlImporter(
            options['db_path'], options['doc_path'],
            rerun=options['rerun'],
            reindex=options['reindex'],
            watermark=options['watermark']
        )
        if options['parallel']:
            with Pool(4) as pool:
                pool.map(
                    BGBlImporter.run_task,
                    list(imp.get_tasks())
                )
        else:
            imp.run_import()
