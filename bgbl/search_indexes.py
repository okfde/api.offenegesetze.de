from django.conf import settings
from elasticsearch_dsl import (
    Document, Date, Integer,
    analyzer, Keyword, Text,
    Index, token_filter
)
from elasticsearch_dsl import connections


connections.create_connection(hosts=[settings.ES_URL], timeout=120)

decomp = token_filter(
    "decomp",
    type='hyphenation_decompounder',
    word_list_path="analysis/dictionary-de.txt",
    hyphenation_patterns_path="analysis/de_DR.xml",
    only_longest_match=True,
    min_subword_size=4
)


og_analyzer = analyzer(
    'og_analyzer',
    tokenizer='standard',
    filter=[
        'keyword_repeat',
        decomp,

        'lowercase',
        token_filter('stop_de', type='stop', stopwords="_german_"),

        'german_normalization',
        'asciifolding',

        token_filter('de_stemmer', type='stemmer', name='light_german'),
        'remove_duplicates'
    ],
)

og_quote_analyzer = analyzer(
    'og_quote_analyzer',
    tokenizer='standard',
    filter=[
        'keyword_repeat',
        'lowercase',
        'german_normalization',
        'asciifolding',
        token_filter('de_stemmer', type='stemmer', name='light_german'),
        token_filter('unique_stem', type='unique', only_on_same_position=True)
    ],
)

index = Index('offenegesetze_publications')
index.settings(
    number_of_shards=1,
    number_of_replicas=0
)


@index.document
class Publication(Document):
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
        search_analyzer=og_analyzer,
        search_quote_analyzer=og_quote_analyzer,
        index_options='offsets'
    )
    law_date = Date()
    pdf_page = Integer()
    content = Text(
        analyzer=og_analyzer,
        search_analyzer=og_analyzer,
        search_quote_analyzer=og_quote_analyzer,
        index_options='offsets'
    )


def _destroy_index():
    index.delete()


def init_es():
    if not index.exists():
        Publication.init()
