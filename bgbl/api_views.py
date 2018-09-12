import elasticsearch

from elasticsearch_dsl import Q

from django.conf import settings
from django.urls import reverse

from rest_framework import viewsets, serializers, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.filters import BaseFilterBackend
from rest_framework.compat import (
    coreapi, coreschema
)

from .renderers import RSSRenderer
from .search_indexes import Publication as PublicationIndex


def make_dict(hit):
    d = hit.to_dict()
    d['id'] = hit.meta.id
    if hasattr(hit.meta, 'highlight'):
        d['content__highlight'] = list(hit.meta.highlight.content)
    return d


class ElasticResultMixin(object):
    def to_representation(self, instance):
        return super().to_representation(make_dict(instance))


class PublicationSerializer(ElasticResultMixin, serializers.Serializer):
    id = serializers.CharField()
    kind = serializers.CharField()
    year = serializers.IntegerField()
    number = serializers.IntegerField()
    date = serializers.DateTimeField(required=False)

    url = serializers.SerializerMethodField()
    api_url = serializers.SerializerMethodField()
    document_url = serializers.SerializerMethodField()

    order = serializers.IntegerField()
    title = serializers.CharField(required=False)
    law_date = serializers.DateTimeField(required=False)
    page = serializers.IntegerField(required=False)
    pdf_page = serializers.IntegerField(required=False)
    num_pages = serializers.IntegerField()

    content__highlight = serializers.ListField(
        child=serializers.CharField(),
        required=False
    )

    def get_url(self, obj):
        return self.get_document_url(obj)

    def get_api_url(self, obj):
        return settings.API_URL + reverse(
            'api:veroeffentlichung-detail', kwargs={'pk': obj['id']}
        )

    def get_document_url(self, obj):
        return (
            'https://media.offenegesetze.de'
            '/{kind}/{year}/{kind}_{year}_{number}.pdf'.format(**obj) +
            '#page={}'.format(obj['pdf_page']) if obj['pdf_page'] else ''
        )


class PublicationDetailSerializer(PublicationSerializer):
    content = serializers.ListField(
        child=serializers.CharField()
    )


class PublicationFilter(BaseFilterBackend):
    def filter_queryset(self, request, queryset, view):
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
            queryset = queryset.filter('term', **filters)

        filter_page = request.GET.get('page')
        if filter_page:
            queryset = queryset.filter(
                'nested',
                path='entries',
                query=Q('term', entries__page=filter_page)
            )

        q = request.GET.get('q')
        if q:
            queryset = queryset.query(
                Q('multi_match', query=q, fields=['title', 'content'])
            )
            queryset = queryset.highlight('title')

        queryset = queryset.sort(
            '-date', 'kind', 'order'
        )

        return queryset

    def get_schema_fields(self, view):
        return [
            coreapi.Field(
                name='q',
                required=False,
                location='query',
                schema=coreschema.String(
                    title='Query',
                    description='Query with Lucene syntax'
                )
            ),
            coreapi.Field(
                name='year',
                required=False,
                location='query',
                schema=coreschema.String(
                    title='Year',
                    description='Query by year'
                )
            ),
            coreapi.Field(
                name='number',
                required=False,
                location='query',
                schema=coreschema.String(
                    title='Number',
                    description='Query by issue number'
                )
            ),
            coreapi.Field(
                name='kind',
                required=False,
                location='query',
                schema=coreschema.String(
                    title='Kind',
                    description='Kind of publication'
                )
            ),
            coreapi.Field(
                name='page',
                required=False,
                location='query',
                schema=coreschema.String(
                    title='Page',
                    description='Query by page of issue'
                )
            ),
        ]


class PublicationViewSet(viewsets.ReadOnlyModelViewSet):
    filter_backends = (PublicationFilter,)
    renderer_classes = viewsets.ViewSet.renderer_classes + [RSSRenderer]
    queryset = PublicationIndex.search()

    serializer_action_classes = {
        'list': PublicationSerializer,
        'retrieve': PublicationDetailSerializer
    }

    def get_serializer_class(self):
        try:
            return self.serializer_action_classes[self.action]
        except (KeyError, AttributeError):
            return PublicationSerializer

    @action(detail=False, renderer_classes=(RSSRenderer,))
    def rss(self, request):
        return self.list(request)

    def retrieve(self, request, pk=None):
        try:
            instance = PublicationIndex.get(id=pk)
        except elasticsearch.exceptions.NotFoundError:
            return Response(status=status.HTTP_404_NOT_FOUND)
        serializer = self.get_serializer(instance)
        return Response(serializer.data)
