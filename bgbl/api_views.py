from collections import OrderedDict

import elasticsearch
from elasticsearch_dsl import (
    FacetedSearch, TermsFacet, DateHistogramFacet
)
from django.conf import settings
from django.urls import reverse

from rest_framework import viewsets, serializers, status
from rest_framework.decorators import action
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.response import Response
from rest_framework.filters import BaseFilterBackend
from rest_framework.compat import (
    coreapi, coreschema
)

from .renderers import RSSRenderer
from .search_indexes import Publication


def make_dict(hit):
    d = hit.to_dict()
    d['id'] = hit.meta.id
    if getattr(hit.meta, 'score', None):
        d['score'] = hit.meta.score
    if hasattr(hit.meta, 'highlight'):
        for key in hit.meta.highlight:
            d['%s__highlight' % key] = list(hit.meta.highlight[key])
    return d


def dump_facets(facets):
    return {
        key: [{
            'value': tag,
            'count': count,
            'selected': selected
        } for (tag, count, selected) in facets[key]
        ] for key in facets
    }


class PublicationSearch(FacetedSearch):
    doc_types = [Publication]
    fields = ['title', 'content']

    facets = {
        'kind': TermsFacet(field='kind'),
        'year': TermsFacet(field='year'),
        'number': TermsFacet(field='number'),
        'date': DateHistogramFacet(
            field='date', interval='year'
        )
    }


class ElasticResultMixin(object):
    def to_representation(self, instance):
        ret = super().to_representation(make_dict(instance))
        return ret


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

    title__highlight = serializers.ListField(
        child=serializers.CharField(),
        required=False
    )
    content__highlight = serializers.ListField(
        child=serializers.CharField(),
        required=False
    )
    score = serializers.FloatField(
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

        filter_page = request.GET.get('page')
        if filter_page:
            filters['page'] = filter_page

        query = request.GET.get('q')

        sort = ('-date', 'kind', 'order')
        if query is not None:
            sort = ('_score',)

        queryset = PublicationSearch(
            query=query,
            filters=filters,
            sort=sort
        )
        print(queryset._s.to_dict())
        return queryset.execute()

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


class CustomLimitOffsetPagination(LimitOffsetPagination):
    def get_paginated_response(self, data):
        return Response(OrderedDict([
            ('count', self.count),
            ('next', self.get_next_link()),
            ('previous', self.get_previous_link()),
            ('results', data['results']),
            ('facets', dump_facets(data['facets']))
        ]))


class PublicationViewSet(viewsets.ReadOnlyModelViewSet):
    filter_backends = (PublicationFilter,)
    renderer_classes = viewsets.ViewSet.renderer_classes + [RSSRenderer]
    queryset = Publication.search()
    pagination_class = CustomLimitOffsetPagination

    serializer_action_classes = {
        'list': PublicationSerializer,
        'retrieve': PublicationDetailSerializer
    }

    def get_serializer_class(self):
        try:
            return self.serializer_action_classes[self.action]
        except (KeyError, AttributeError):
            return PublicationSerializer

    def list(self, request):
        queryset = self.filter_queryset(self.get_queryset())
        print('queryset', queryset)
        page = self.paginate_queryset(queryset)
        if page is not None:
            print('PAGE', page)
            serializer = self.get_serializer(page, many=True)

            return self.get_paginated_response({
                'results': serializer.data,
                'facets': queryset.facets
            })
        print('PAGENONE')
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    @action(detail=False, renderer_classes=(RSSRenderer,))
    def rss(self, request):
        return self.list(request)

    def retrieve(self, request, pk=None):
        try:
            instance = Publication.get(id=pk)
        except elasticsearch.exceptions.NotFoundError:
            return Response(status=status.HTTP_404_NOT_FOUND)
        serializer = self.get_serializer(instance)
        return Response(serializer.data)
