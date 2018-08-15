from django.conf import settings
from elasticsearch_dsl import (
    DocType, Date, Nested, Double, Integer,
    analyzer, InnerDoc, Keyword, Text,
    Index
)
from elasticsearch_dsl import connections


connections.create_connection(hosts=[settings.ES_URL], timeout=20)

og_analyzer = analyzer(
    'og_analyzer',
    tokenizer="standard",
    filter=["standard", "asciifolding", "lowercase"],
)


class PublicationEntry(InnerDoc):
    title = Keyword()
    law_date = Date()
    page = Integer()


class Publication(DocType):
    kind = Keyword()
    year = Integer()
    number = Integer()
    date = Date()
    page = Integer()
    content = Text(fields={'raw': Keyword()}, analyzer=og_analyzer)

    entries = Nested(PublicationEntry)


og_publication = Index('offenegesetze_publications')
og_publication.settings(
    number_of_shards=1,
    number_of_replicas=0
)

og_publication.doc_type(Publication)
og_publication.analyzer(og_analyzer)


def _destroy_index():
    og_publication.delete()


def init_es():
    if not og_publication.exists():
        og_publication.create()

    Publication.init()
