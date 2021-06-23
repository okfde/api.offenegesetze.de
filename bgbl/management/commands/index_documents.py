import datetime
from multiprocessing import Pool

from django.core.management.base import BaseCommand

from bgbl.search_indexes import (
    _destroy_index, init_es
)
from bgbl.importer import BGBlImporter


def create_range_argument(arg):
    if arg is None:
        return None

    def generator(args):
        for part in parts:
            part = part.strip()
            if '-' in part:
                start_stop = part.split('-')
                yield from range(int(start_stop[0]), int(start_stop[1]) + 1)
            else:
                yield int(part)

    arg = str(arg)
    parts = arg.split(',')
    return list(generator(parts))


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
        parser.add_argument('--years', dest='years', action='store',
                            default=str(datetime.datetime.now().year),
                            help='Scrape these years, default latest year. '
                                 'Range and comma-separated allowed.')
        parser.add_argument('--numbers', dest='numbers', action='store',
                            default=None,
                            help='Scrape these numbers, default all.')
        parser.add_argument('--parts', dest='parts', action='store',
                            default='1,2',
                            help='Scrape parts, default all parts. '
                                 'Range and comma-separated allowed.')

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
            watermark=options['watermark'],
            years=create_range_argument(options['years']),
            parts=create_range_argument(options['parts']),
            numbers=create_range_argument(options['numbers']),
        )
        if options['parallel']:
            with Pool(4) as pool:
                pool.map(
                    BGBlImporter.run_task,
                    list(imp.get_tasks())
                )
        else:
            imp.run_import()
