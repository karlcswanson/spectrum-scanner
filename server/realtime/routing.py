"""WebSocket URL routing."""

from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    re_path(r'ws/scans/$', consumers.ScanConsumer.as_asgi()),
    re_path(r'ws/scans/(?P<scanner_id>\w+)/$', consumers.ScanConsumer.as_asgi()),
]
