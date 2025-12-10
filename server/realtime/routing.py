"""
DEPRECATED: WebSocket routing is no longer used.

Frontend now connects directly to MQTT broker over WebSocket (port 9001)
for real-time scan data. This eliminates the need for Django Channels.

This file is kept for reference only and can be safely deleted.
"""

websocket_urlpatterns = []
