import elasticsearch

from elasticsearch_dsl import Q

from django.conf import settings
from django.urls import reverse

from rest_framework import viewsets, serializers, status
from rest_framework.decorators import action
from rest_framework.response import Response

from .renderers import RSSRenderer
from .search_indexes import Publication as PublicationIndex


class PublicationEntrySerializer(serializers.Serializer):
    order = serializers.IntegerField()
    title = serializers.CharField(required=False)
    law_date = serializers.DateTimeField(required=False)
    page = serializers.IntegerField(required=False)
    anchor = serializers.SerializerMethodField()

    def get_anchor(self, obj):
        return '#%s' % obj['order']


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
    url = serializers.SerializerMethodField()
    api_url = serializers.SerializerMethodField()
    document_url = serializers.SerializerMethodField()

    def get_url(self, obj):
        return self.get_document_url(obj)

    def get_api_url(self, obj):
        return settings.API_URL + reverse(
            'api:amtsblatt-detail', kwargs={'pk': obj['id']}
        )

    def get_document_url(self, obj):
        return (
            'https://media.offenegesetze.de'
            '/{kind}/{year}/{kind}_{year}_{number}.pdf'.format(**obj)
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

    s = s.sort(
        '-date',
    )

    return s


class PublicationViewSet(viewsets.ViewSet):
    renderer_classes = viewsets.ViewSet.renderer_classes + [RSSRenderer]

    def list(self, request):
        s = PublicationIndex.search()
        s = filter_search(s, request)
        results = s.execute()
        serializer = PublicationSerializer(
            [make_dict(hit) for hit in results], many=True
        )
        return Response(serializer.data)

    @action(detail=False, renderer_classes=(RSSRenderer,))
    def rss(self, request):
        return self.list(request)

    def retrieve(self, request, pk=None):
        try:
            pub = PublicationIndex.get(id=pk)
        except elasticsearch.exceptions.NotFoundError:
            return Response(status=status.HTTP_404_NOT_FOUND)
        serializer = PublicationDetailSerializer(make_dict(pub))
        return Response(serializer.data)
