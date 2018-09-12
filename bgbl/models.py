import os

from django.db import models


class Publication(models.Model):
    kind = models.CharField(max_length=25, choices=(
        ('bgbl1', 'BGBL I'),
        ('bgbl2', 'BGBL II'),
    ))
    year = models.PositiveIntegerField()
    number = models.PositiveIntegerField()
    date = models.DateField()
    page = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        ordering = ('kind', 'number')

    def __str__(self):
        return '%s: %s-%s' % (self.kind, self.year, self.number)

    def get_path(self, base_path):
        return os.path.join(
            base_path,
            '{kind}/{year}/{kind}_{year}_{number}.pdf'.format(
                kind=self.kind,
                year=self.year,
                number=self.number
            ))


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
