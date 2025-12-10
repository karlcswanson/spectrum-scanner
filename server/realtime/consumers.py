"""
DEPRECATED: WebSocket consumers are no longer used.

Frontend now connects directly to MQTT broker over WebSocket (port 9001)
for real-time scan data. This eliminates the need for Django Channels.

This file is kept for reference only and can be safely deleted.
"""

# The ScanConsumer class that was here has been removed.
# See server/realtime/mqtt_bridge.py for MQTT message handling
# and database storage.
