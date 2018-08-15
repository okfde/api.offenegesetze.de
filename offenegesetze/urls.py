"""offenegesetze URL Configuration

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/2.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include

from rest_framework.routers import DefaultRouter
from rest_framework.schemas import get_schema_view

from bgbl.api_views import PublicationViewSet

api_router = DefaultRouter()

api_router.register(r'bgbl', PublicationViewSet, base_name='bgbl')

urlpatterns = [
    path('admin/', admin.site.urls),
]


schema_view = get_schema_view(title='Offenegesetze.de API')
urlpatterns += [
    path('api/v1/', include((api_router.urls, 'api'))),
    path('api/v1/schema/', schema_view),
]
