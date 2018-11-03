import os

from django.db import models

PUBLICATIONS = (
    ('bgbl1', 'BGBl Teil I'),
    ('bgbl2', 'BGBl Teil II'),
)

PUBLICATIONS_DICT = dict(PUBLICATIONS)


class PublicationManager(models.Manager):
    def get_from_filename(self, filename):
        filename = os.path.basename(filename)
        filename = filename.split('.')[0]
        kind, year, number = filename.split('_', 3)
        return Publication.objects.get(
            kind=kind,
            year=int(year),
            number=int(number)
        )


class Publication(models.Model):
    kind = models.CharField(max_length=25, choices=PUBLICATIONS)
    year = models.PositiveIntegerField()
    number = models.PositiveIntegerField()
    date = models.DateField()
    page = models.PositiveIntegerField(null=True, blank=True)

    objects = PublicationManager()

    class Meta:
        ordering = ('kind', 'number')

    def __str__(self):
        return '%s: %s-%s' % (self.kind, self.year, self.number)

    @property
    def title(self):
        kind = PUBLICATIONS_DICT.get(self.kind, self.kind)
        return '{kind} Nr. {number} Jahr {year}'.format(
            kind=kind, number=self.number, year=self.year
        )

    def get_path(self, base_path):
        return os.path.join(
            base_path,
            '{kind}/{year}/{kind}_{year}_{number}.pdf'.format(
                kind=self.kind,
                year=self.year,
                number=self.number
            ))

    def has_likely_watermark(self):
        if self.kind == 'bgbl1':
            return self.date.year >= 2009
        if self.kind == 'bgbl2':
            return self.date.year >= 2005


class PublicationEntry(models.Model):
    publication = models.ForeignKey(
        Publication, on_delete=models.CASCADE, related_name='entries'
    )
    order = models.PositiveIntegerField()
    title = models.TextField(blank=True)
    law_date = models.DateField(null=True, blank=True)
    page = models.PositiveIntegerField(null=True, blank=True)
    pdf_page = models.PositiveIntegerField(null=True, blank=True)
    num_pages = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ('page',)

    def __str__(self):
        return self.title
