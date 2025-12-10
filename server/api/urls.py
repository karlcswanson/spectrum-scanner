"""API URL configuration."""

from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import ScannerViewSet, BandViewSet, ScanViewSet

router = DefaultRouter()
router.register(r'scanners', ScannerViewSet)
router.register(r'bands', BandViewSet)
router.register(r'scans', ScanViewSet)

urlpatterns = [
    path('', include(router.urls)),
]
