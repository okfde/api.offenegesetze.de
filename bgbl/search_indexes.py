from django.conf import settings
from elasticsearch_dsl import (
    DocType, Date, Integer,
    analyzer, Keyword, Text,
    Index, token_filter
)
from elasticsearch_dsl import connections


connections.create_connection(hosts=[settings.ES_URL], timeout=20)

og_analyzer = analyzer(
    'og_analyzer',
    tokenizer='standard',
    filter=[
        'standard',
        'lowercase',
        'keyword_repeat',
        token_filter('stop_de', type='stop', stopwords="_german_"),
        'asciifolding',
        # 'word_delimiter', # Breaks indexing
        token_filter('decomp', type='decompound'),
        token_filter('de_stemmer', type='stemmer', name='light_german'),
        token_filter('unique_stem', type='unique', only_on_same_position=True)
    ],
)


class Publication(DocType):
    kind = Keyword()
    year = Integer()
    number = Integer()
    date = Date()
    page = Integer()
    order = Integer()
    num_pages = Integer()
    title = Text(
        fields={'raw': Keyword()},
        analyzer=og_analyzer,
        index_options='offsets'
    )
    law_date = Date()
    pdf_page = Integer()
    content = Text(
        fields={'raw': Keyword()},
        analyzer=og_analyzer,
        index_options='offsets'
    )


og_publication = Index('offenegesetze_publications')
og_publication.settings(
    number_of_shards=1,
    number_of_replicas=0
)

og_publication.doc_type(Publication)
og_publication.analyzer(og_analyzer)
# og_publication.settings(**{"index.highlight.max_analyzed_offset": 10000})


def _destroy_index():
    og_publication.delete()


def init_es():
    if not og_publication.exists():
        og_publication.create()
