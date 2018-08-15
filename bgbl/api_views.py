from elasticsearch import Elasticsearch

from elasticsearch_dsl import Q

from rest_framework import viewsets, serializers
from rest_framework.response import Response

from .search_indexes import Publication as PublicationIndex

es_client = Elasticsearch()


class PublicationEntrySerializer(serializers.Serializer):
    order = serializers.IntegerField()
    title = serializers.CharField(required=False)
    law_date = serializers.DateTimeField(required=False)
    page = serializers.IntegerField(required=False)


class PublicationSerializer(serializers.Serializer):
    id = serializers.CharField()
    kind = serializers.CharField()
    year = serializers.IntegerField()
    number = serializers.IntegerField()
    date = serializers.DateTimeField(required=False)
    page = serializers.IntegerField(required=False)
    entries = serializers.ListField(
        child=PublicationEntrySerializer(),
        required=False
    )


class PublicationDetailSerializer(PublicationSerializer):
    content = serializers.ListField(
        child=serializers.CharField()
    )


def make_dict(hit):
    d = hit.to_dict()
    d['id'] = hit.meta.id
    return d


def filter_search(s, request):
    filters = {}

    year = request.GET.get('year')
    if year:
        filters['year'] = year

    number = request.GET.get('number')
    if number:
        filters['number'] = number

    kind = request.GET.get('kind')
    if kind:
        filters['kind'] = kind

    if filters:
        s = s.filter('term', **filters)

    page = request.GET.get('page')
    if page:
        s = s.filter(
            'nested',
            path='entries',
            query=Q('term', entries__page=page)
        )

    q = request.GET.get('q')
    if q:
        s = s.query(
            Q('match', content=q) |
            Q('nested', path='entries',
                query=Q("match", **{'entries.title': q}))
        )

    return s


class PublicationViewSet(viewsets.ViewSet):
    def list(self, request):
        s = PublicationIndex.search()
        s = filter_search(s, request)
        results = s.execute()
        serializer = PublicationSerializer(
            [make_dict(hit) for hit in results], many=True
        )
        return Response(serializer.data)

    def retrieve(self, request, pk=None):
        pub = PublicationIndex.get(id=pk)
        serializer = PublicationDetailSerializer(make_dict(pub))
        return Response(serializer.data)
