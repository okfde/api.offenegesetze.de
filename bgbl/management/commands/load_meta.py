from datetime import date
from django.core.management.base import BaseCommand

import dataset

from bgbl.models import Publication, PublicationEntry

FIX_LIST = {
    '14.40.2016': '14.04.2016',
    '31.09.1998': '31.08.1998',
    '09.6..06.0': '06.06.2009',
    '09.1..15.0': '15.01.2009',
    '09.3..13.0': '13.03.2009',
    '09.4..21.0': '21.04.2009',
    '08.20.0808': '08.08.2008',
    '09.24.1990': '24.09.1990',
}


def make_date(val):
    if val is None:
        return None
    print(val)
    val = FIX_LIST.get(val, val)
    return date(
        *[int(x) for x in val.split('.')][::-1]
    )


class Command(BaseCommand):
    help = 'Load meta data from scraper'

    def add_arguments(self, parser):
        parser.add_argument('db', type=str)
        parser.add_argument("-r", action='store_true',
                            dest='rerun')

    def handle(self, *args, **options):
        rerun = options['rerun']
        db = dataset.connect('sqlite:///' + options['db'])
        for part in (1, 2,):
            self.handle_part(db, part, rerun=rerun)

    def handle_part(self, db, part, rerun=False):
        publication = None
        publication_key = None
        table = db['data']
        entries = table.find(part=part, order_by=['-year', '-number'])
        for entry in entries:
            entry_pub_key = (entry['part'], entry['year'], entry['number'])
            if entry_pub_key != publication_key:
                publication_key = entry_pub_key
                print(publication_key)
                publication, created = Publication.objects.get_or_create(
                    kind='bgbl%s' % entry['part'],
                    year=entry['year'],
                    number=entry['number'],
                    defaults={
                        'date': make_date(entry['date']),
                        'page': entry['page']
                    }
                )
                if not created and not rerun:
                    print('Skipping')
                    return
                PublicationEntry.objects.filter(
                    publication=publication).delete()
            if entry['kind'] != 'entry':
                continue
            PublicationEntry.objects.create(
                publication=publication,
                title=entry['name'],
                law_date=make_date(entry['law_date']),
                page=entry['page'],
                order=entry['order']
            )
