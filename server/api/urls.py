"""API URL configuration."""

from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import (
    ScannerViewSet, BandViewSet, ScanViewSet,
    mqtt_auth, mqtt_acl, mqtt_superuser, mqtt_credentials,
    auth_user, auth_login, auth_logout,
    share_token_auth, generate_share_link
)

router = DefaultRouter()
router.register(r'scanners', ScannerViewSet)
router.register(r'bands', BandViewSet)
router.register(r'scans', ScanViewSet)

urlpatterns = [
    path('', include(router.urls)),
    # MQTT auth endpoints (called by mosquitto-go-auth plugin)
    path('auth/mqtt/', mqtt_auth, name='mqtt-auth'),
    path('auth/mqtt/acl/', mqtt_acl, name='mqtt-acl'),
    path('auth/mqtt/superuser/', mqtt_superuser, name='mqtt-superuser'),
    # Frontend fetches credentials from here
    path('mqtt/credentials/', mqtt_credentials, name='mqtt-credentials'),
    # User authentication
    path('auth/user/', auth_user, name='auth-user'),
    path('auth/login/', auth_login, name='auth-login'),
    path('auth/logout/', auth_logout, name='auth-logout'),
    # Share links (admin generates, token validates)
    path('share/generate/', generate_share_link, name='share-generate'),
]
