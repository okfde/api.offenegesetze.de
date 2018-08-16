"""offenegesetze URL Configuration

"""
from django.urls import path, include

from rest_framework.routers import DefaultRouter
from rest_framework.schemas import get_schema_view

from bgbl.api_views import PublicationViewSet

api_router = DefaultRouter()

api_router.register(r'bgbl', PublicationViewSet, base_name='bgbl')


schema_view = get_schema_view(title='Offenegesetze.de API')
urlpatterns += [
    path('api/v1/', include((api_router.urls, 'api'))),
    path('api/v1/schema/', schema_view),
]
