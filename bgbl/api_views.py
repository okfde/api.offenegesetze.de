from collections import OrderedDict
import logging
import json

import elasticsearch
from elasticsearch_dsl import (
    FacetedSearch, TermsFacet, DateHistogramFacet
)
from elasticsearch_dsl.faceted_search import Facet
from elasticsearch_dsl.query import Range

from django.conf import settings
from django.db.models import Max
from django.urls import reverse

from rest_framework import viewsets, serializers, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.filters import BaseFilterBackend
from rest_framework.compat import (
    coreapi, coreschema
)
from rest_framework.pagination import (
    PageNumberPagination, CursorPagination,
    _reverse_ordering, _positive_int, Cursor
)
from rest_framework.exceptions import NotFound
from rest_framework.utils.urls import (
    replace_query_param, remove_query_param
)
from rest_framework.settings import api_settings

from .models import Publication as PublicationModel
from .renderers import RSSRenderer
from .search_indexes import Publication

logger = logging.getLogger(name=__name__)


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


class NumberRangeFacet(Facet):
    agg_type = 'terms'

    def get_value_filter(self, filter_value):
        f, t = None, None
        try:
            if '-' in filter_value:
                f, t = filter_value.split('-', 1)
            else:
                t = f = int(filter_value)
            if not f:
                f = None
            else:
                f = int(f)
            if not t:
                t = None
            else:
                t = int(t)
        except ValueError:
            f, t = None, None

        limits = {}
        if f is not None:
            limits['gte'] = f
        if t is not None:
            limits['lte'] = t

        return Range(**{
            self._params['field']: limits
        })


class PublicationSearch(FacetedSearch):
    doc_types = [Publication]
    index = 'offenegesetze_publications'
    fields = ['title^3', 'content']

    facets = {
        'kind': TermsFacet(field='kind'),
        'year': NumberRangeFacet(field='year'),
        'page': NumberRangeFacet(field='page'),
        'number': NumberRangeFacet(field='number'),
        'date': DateHistogramFacet(
            field='date', interval='year'
        )
    }

    def __getitem__(self, n):
        assert isinstance(n, slice)
        self._s = self._s[n]
        return self

    def add_sort(self, *sort_args):
        self._sort = sort_args
        self._s = self._s.sort(*sort_args)

    def add_pagination_filter(self, filter_kwargs):
        self._s = self._s.filter('range', **filter_kwargs)

    def query(self, search, query):
        """
        Add query part to ``search``.
        Override this if you wish to customize the query used.
        """
        if query:
            return search.query(
                'simple_query_string',
                analyzer='og_analyzer',
                fields=self.fields,
                query=query,
                minimum_should_match='80%',
                default_operator='AND',
                lenient=True
            )
        return search


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
        return (
            'https://offenegesetze.de/veroeffentlichung/'
            '{kind}/{year}/{number}'.format(**obj) +
            '#page={}'.format(obj['pdf_page']) if obj.get('pdf_page') else ''
        )

    def get_api_url(self, obj):
        return settings.API_URL + reverse(
            'api:veroeffentlichung-detail', kwargs={'pk': obj['id']}
        )

    def get_document_url(self, obj):
        return (
            'https://media.offenegesetze.de'
            '/{kind}/{year}/{kind}_{year}_{number}.pdf'.format(**obj) +
            '#page={}'.format(obj['pdf_page']) if obj.get('pdf_page') else ''
        )


class PublicationDetailSerializer(PublicationSerializer):
    content = serializers.ListField(
        child=serializers.CharField()
    )


class CustomPageNumberPagination(PageNumberPagination):
    page_query_param = 'p'
    max_page = 10
    page_size = api_settings.PAGE_SIZE

    def paginate_queryset(self, queryset, request, view=None):
        """
        Paginate a queryset if required, either returning a
        page object, or `None` if pagination is not configured for this view.
        """
        self.request = request

        try:
            self.page_number = int(request.query_params.get(
                self.page_query_param, 1
            ))
        except ValueError:
            self.page_number = 1

        if self.page_number > self.max_page:
            raise NotFound('Result page number too high.')

        offset = (self.page_number - 1) * self.page_size
        queryset = queryset[offset:offset + self.page_size]
        self.results = queryset.execute()

        self.page = self.results[:self.page_size]

        return self.results, self.page

    def get_next_link(self):
        if self.page_number >= self.max_page:
            return None
        if self.page_number * self.page_size > self.results.hits.total:
            return None
        url = self.request.build_absolute_uri()
        page_number = self.page_number + 1
        return replace_query_param(url, self.page_query_param, page_number)

    def get_previous_link(self):
        if self.page_number <= 1:
            return None
        url = self.request.build_absolute_uri()
        page_number = self.page_number - 1
        if page_number == 1:
            return remove_query_param(url, self.page_query_param)
        return replace_query_param(url, self.page_query_param, page_number)


class FilterPagination(CursorPagination):
    page_size = api_settings.PAGE_SIZE
    cursor_query_param = 'offset'
    ordering = ('-date', 'kind', 'order')

    def paginate_queryset(self, queryset, request, view=None):
        """
        Paginate a queryset if required, either returning a
        page object, or `None` if pagination is not configured for this view.
        """
        self.page_number_pagination = None
        if request.GET.get('q'):
            self.page_number_pagination = CustomPageNumberPagination()
            return self.page_number_pagination.paginate_queryset(
                queryset, request, view=view
            )

        self.base_url = request.build_absolute_uri()
        self.ordering = self.get_ordering(request, queryset, view)

        self.cursor = self.decode_cursor(request)
        if self.cursor is None:
            (offset, reverse, current_position) = (0, False, None)
        else:
            (offset, reverse, current_position) = self.cursor

        # Cursor pagination always enforces an ordering.
        if reverse:
            queryset.add_sort(*_reverse_ordering(self.ordering))
        else:
            queryset.add_sort(*self.ordering)

        # If we have a cursor with a fixed position then filter by that.
        if current_position is not None:
            order = self.ordering[0]
            is_reversed = order.startswith('-')
            order_attr = order.lstrip('-')

            # Test for: (cursor reversed) XOR (queryset reversed)
            if self.cursor.reverse != is_reversed:
                kwargs = {order_attr: {'lt': current_position}}
            else:
                kwargs = {order_attr: {'gt': current_position}}

            queryset.add_pagination_filter(kwargs)

        # If we have an offset cursor then offset the entire page by that amount.
        # We also always fetch an extra item in order to determine if there is a
        # page following on from this one.
        queryset = queryset[offset:offset + self.page_size + 1]
        logger.debug('ES query: %s', json.dumps(queryset._s.to_dict()))
        results = queryset.execute()

        self.page = results[:self.page_size]
        if reverse:
            self.page = list(reversed(self.page))

        # Determine the position of the final item following the page.
        if len(results) > len(self.page):
            has_following_position = True
            following_position = self._get_position_from_instance(
                results[-1], self.ordering
            )
        else:
            has_following_position = False
            following_position = None

        if reverse:
            # If we have a reverse queryset, then the query ordering was in reverse
            # so we need to reverse the items again before returning them to the user.

            # Determine next and previous positions for reverse cursors.
            self.has_next = (current_position is not None) or (offset > 0)
            self.has_previous = has_following_position
            if self.has_next:
                self.next_position = current_position
            if self.has_previous:
                self.previous_position = following_position
        else:
            # Determine next and previous positions for forward cursors.
            self.has_next = has_following_position
            self.has_previous = (current_position is not None) or (offset > 0)
            if self.has_next:
                self.next_position = following_position
            if self.has_previous:
                self.previous_position = current_position

        # Display page controls in the browsable API if there is more
        # than one page.
        if (self.has_previous or self.has_next) and self.template is not None:
            self.display_page_controls = True

        return results, self.page

    def _get_position_from_instance(self, instance, ordering):
        field_name = ordering[0].lstrip('-')
        attr = getattr(instance, field_name)
        if attr:
            return str(attr).split(' ')[0]
        return None

    def decode_cursor(self, request):
        """
        Given a request with a cursor, return a `Cursor` instance.
        """
        # Determine if we have a cursor, and if so then decode it.
        encoded = request.query_params.get(self.cursor_query_param)
        if encoded is None:
            return None

        try:
            reverse = False
            if encoded.startswith('-'):
                encoded = encoded[1:]
                reverse = True

            offset = 0
            parts = encoded.split('+', 1)
            if '-' in parts[0]:
                position = parts[0]
            else:
                position = None

            if len(parts) > 1:
                offset = _positive_int(parts[1], cutoff=self.offset_cutoff)

        except (TypeError, ValueError):
            raise NotFound(self.invalid_cursor_message)

        return Cursor(offset=offset, reverse=reverse, position=position)

    def encode_cursor(self, cursor):
        """
        Given a Cursor instance, return an url with encoded cursor.
        """
        if cursor.position is None:
            encoded = ''
        else:
            encoded = cursor.position
        if cursor.reverse:
            encoded = '-' + encoded
        if cursor.offset != 0:
            encoded += '+%s' % cursor.offset

        return replace_query_param(
            self.base_url, self.cursor_query_param, encoded
        )

    def get_next_link(self):
        if self.page_number_pagination:
            return self.page_number_pagination.get_next_link()
        if len(self.page) == 0:
            return None
        return super().get_next_link()

    def get_previous_link(self):
        if self.page_number_pagination:
            return self.page_number_pagination.get_previous_link()
        if len(self.page) == 0:
            return None
        return super().get_previous_link()

    def get_paginated_response(self, data):
        return Response(OrderedDict([
            ('count', data['count']),
            ('next', self.get_next_link()),
            ('previous', self.get_previous_link()),
            ('results', data['results']),
            ('facets', dump_facets(data['facets']))
        ]))


class PublicationFilter(BaseFilterBackend):
    def filter_queryset(self, request, queryset, view):
        filters = {}

        year = request.GET.getlist('year')
        if year:
            filters['year'] = year

        number = request.GET.getlist('number')
        if number:
            filters['number'] = number

        kind = request.GET.getlist('kind')
        if kind:
            filters['kind'] = kind

        filter_page = request.GET.getlist('page')
        if filter_page:
            filters['page'] = filter_page

        query = request.GET.get('q')

        sort = None
        if query and not request.GET.get('format') == 'rss':
            sort = ('_score',)

        queryset = PublicationSearch(
            query=query,
            filters=filters,
            sort=sort
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
    pagination_class = FilterPagination

    serializer_action_classes = {
        'list': PublicationSerializer,
        'retrieve': PublicationDetailSerializer
    }

    def get_serializer_class(self):
        if self.action == 'list':
            has_filters = all(self.request.GET.get(x)
                              for x in ('year', 'kind', 'number'))
            if has_filters:
                return PublicationDetailSerializer
            return PublicationSerializer
        elif self.action == 'list':
            return PublicationDetailSerializer
        return PublicationSerializer

    def get_queryset(self):
        queryset = Publication.search()
        return queryset

    def list(self, request):
        queryset = self.filter_queryset(self.get_queryset())
        results, page = self.paginate_queryset(queryset)

        serializer = self.get_serializer(page, many=True)
        return self.get_paginated_response({
            'results': serializer.data,
            'facets': results.facets,
            'count': results.hits.total
        })

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

    @action(detail=False, methods=['get'])
    def overview(self, request):
        numbers = list(
            PublicationModel.objects
            .values('kind', 'year')
            .order_by('kind', 'year')
            .annotate(max_number=Max('number'))
        )
        return Response(numbers)
