from django.conf import settings
from django.urls import reverse

from rest_framework import renderers

from feedgen.feed import FeedGenerator


class RSSRenderer(renderers.BaseRenderer):
    """
    Renderer which serializes to CustomXML.
    """

    media_type = 'application/xml'
    format = 'rss'
    charset = 'utf-8'

    def render(self, data, accepted_media_type=None, renderer_context=None):
        """
        Renders *data* into serialized XML.
        """
        if data is None:
            return ''

        fg = FeedGenerator()
        feed_url = settings.API_URL + reverse('api:amtsblatt-list')
        feed_title = 'OffeneGesetze.de'
        feed_description = 'Feed für Veröffentlichungen des Bundesgesetzblatts'

        fg.id(feed_url)
        fg.title(feed_title)
        fg.subtitle(feed_description)
        fg.link(href=feed_url, rel='alternate')
        # fg.logo('https://offenegesetze.de/img/logo.png')
        fg.link(href=feed_url + '?format=rss', rel='self')
        fg.language('de')
        fg.generator('')

        if not isinstance(data, list):
            data = [data]

        for item in data:
            for entry in item['entries']:
                fe = fg.add_entry()
                fe.id('%s/%s#%s' % (
                    settings.SITE_URL, item['id'], entry['order'])
                )
                fe.pubDate(item['date'])
                fe.title(entry['title'])
                fe.link({'href': item['url'] + entry['anchor']})
                fe.content(entry['title'])
                # fe.description(item['description'])

        return fg.rss_str(pretty=True)
