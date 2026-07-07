"""API URL configuration."""

from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import (
    ScannerViewSet, BandViewSet, ScanViewSet, ScannerGroupViewSet,
    MonitoredFrequencyViewSet,
    mqtt_credentials,
    auth_user, auth_login, auth_logout,
    share_token_auth, generate_share_link,
    list_access, create_access, revoke_access,
)

router = DefaultRouter()
router.register(r'scanners', ScannerViewSet)
router.register(r'bands', BandViewSet)
router.register(r'scans', ScanViewSet)
router.register(r'groups', ScannerGroupViewSet)
router.register(r'monitored-frequencies', MonitoredFrequencyViewSet)

urlpatterns = [
    path('', include(router.urls)),
    # Frontend fetches MQTT credentials (provisions dynsec client lazily)
    path('mqtt/credentials/', mqtt_credentials, name='mqtt-credentials'),
    # User authentication
    path('auth/user/', auth_user, name='auth-user'),
    path('auth/login/', auth_login, name='auth-login'),
    path('auth/logout/', auth_logout, name='auth-logout'),
    # Share links (admin generates, token validates)
    path('share/generate/', generate_share_link, name='share-generate'),
    # Access management
    path('access/', list_access, name='access-list'),
    path('access/create/', create_access, name='access-create'),
    path('access/<uuid:pk>/revoke/', revoke_access, name='access-revoke'),
]
