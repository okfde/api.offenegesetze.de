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
        feed_url = settings.API_URL + reverse('api:veroeffentlichung-list')
        feed_title = 'OffeneGesetze.de'
        feed_description = 'Feed für Veröffentlichungen des Bundesgesetzblatts'

        fg.id(feed_url)
        fg.title(feed_title)
        fg.subtitle(feed_description)
        fg.link(href=feed_url, rel='alternate')
        fg.logo('https://offenegesetze.de/apple-touch-icon.png')
        fg.link(href=feed_url + '?format=rss', rel='self')
        fg.language('de')
        fg.generator('')

        if not isinstance(data, list):
            data = [data]

        results = reversed(data[0]['results'])

        for item in results:
            fe = fg.add_entry()
            fe.id('%s/%s' % (
                settings.SITE_URL, item['id'])
            )
            fe.pubDate(item['date'])
            fe.title(item['title'])
            fe.link({'href': item['url']})
            if 'content' in item:
                fe.description(
                    item['content'] if isinstance(item['content'], str)
                    else ''.join(item['content'])
                )

        return fg.rss_str(pretty=True)
