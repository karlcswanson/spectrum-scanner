"""MQTT to Django Channels bridge.

This module connects to the MQTT broker and forwards scan data
to Django Channels for WebSocket distribution.

Run as a Django management command:
    python manage.py mqtt_bridge
"""

import json
import logging
from datetime import datetime

import paho.mqtt.client as mqtt
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)


class MQTTBridge:
    """Bridges MQTT messages to Django Channels."""

    def __init__(self):
        self.client = mqtt.Client(
            client_id=settings.MQTT_CLIENT_ID,
            protocol=mqtt.MQTTv5,
        )
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        self.client.on_disconnect = self.on_disconnect

        self.channel_layer = get_channel_layer()
        self.topic_prefix = settings.MQTT_TOPIC_PREFIX

    def connect(self):
        """Connect to MQTT broker."""
        logger.info(f"Connecting to MQTT broker at {settings.MQTT_BROKER_HOST}:{settings.MQTT_BROKER_PORT}")
        self.client.connect(
            settings.MQTT_BROKER_HOST,
            settings.MQTT_BROKER_PORT,
            keepalive=60,
        )

    def on_connect(self, client, userdata, flags, reason_code, properties=None):
        """Called when connected to MQTT broker."""
        if reason_code == 0:
            logger.info("Connected to MQTT broker")

            # Subscribe to scan data from all scanners
            scan_topic = f"{self.topic_prefix}/scanners/+/scan"
            client.subscribe(scan_topic)
            logger.info(f"Subscribed to {scan_topic}")

            # Subscribe to status updates
            status_topic = f"{self.topic_prefix}/scanners/+/status"
            client.subscribe(status_topic)
            logger.info(f"Subscribed to {status_topic}")

            # Subscribe to config updates (retained, sent on scanner connect)
            config_topic = f"{self.topic_prefix}/scanners/+/config"
            client.subscribe(config_topic)
            logger.info(f"Subscribed to {config_topic}")
        else:
            logger.error(f"Failed to connect to MQTT: {reason_code}")

    def on_disconnect(self, client, userdata, reason_code, properties=None):
        """Called when disconnected from MQTT broker."""
        logger.warning(f"Disconnected from MQTT broker: {reason_code}")

    def on_message(self, client, userdata, msg):
        """Called when a message is received from MQTT."""
        try:
            topic_parts = msg.topic.split('/')
            # Expected: spectrum/scanners/{scanner_id}/{message_type}
            if len(topic_parts) >= 4:
                scanner_id = topic_parts[2]
                message_type = topic_parts[3]

                payload = json.loads(msg.payload.decode('utf-8'))

                if message_type == 'scan':
                    self.handle_scan(scanner_id, payload)
                elif message_type == 'status':
                    self.handle_status(scanner_id, payload)
                elif message_type == 'config':
                    self.handle_config(scanner_id, payload)

        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in MQTT message: {e}")
        except Exception as e:
            logger.error(f"Error processing MQTT message: {e}")

    def handle_scan(self, scanner_id: str, payload: dict):
        """Process incoming scan data."""
        logger.debug(f"Received scan from {scanner_id}")

        # Store in database (optional, can be disabled for high-frequency scans)
        self.store_scan(scanner_id, payload)

        # Include scanner_id in the forwarded data
        ws_data = {
            'scanner_id': scanner_id,
            **payload,
        }

        # Forward to WebSocket clients via Channels
        async_to_sync(self.channel_layer.group_send)(
            'scans_all',
            {
                'type': 'scan_data',
                'data': ws_data,
            }
        )

        # Also send to scanner-specific group
        async_to_sync(self.channel_layer.group_send)(
            f'scans_{scanner_id}',
            {
                'type': 'scan_data',
                'data': ws_data,
            }
        )

    def handle_config(self, scanner_id: str, payload: dict):
        """Process scanner config update.

        Payload format:
        {
            "id": "scanner-id",
            "name": "Studio A Scanner",
            "type": "pluto",
            "location": "Studio A",
            "description": "ADALM-Pluto Scanner",
            "bands": [
                {"name": "UHF", "start_hz": 470000000, "stop_hz": 608000000, "enabled": true}
            ],
            "settings": {
                "dwell_time_ms": 200,
                "rx_gain": 40,
                "rx_gain_mode": "manual",
                "mode": "Average"
            }
        }
        """
        from core.models import Scanner, Band

        try:
            logger.info(f"Received config from {scanner_id}: {payload.get('name')}")

            # Update or create scanner
            scanner, created = Scanner.objects.update_or_create(
                id=scanner_id,
                defaults={
                    'name': payload.get('name', scanner_id),
                    'scanner_type': payload.get('type', 'pluto'),
                    'location': payload.get('location', ''),
                    'description': payload.get('description', ''),
                    'online': True,
                    'last_seen': timezone.now(),
                }
            )

            if created:
                logger.info(f"Created new scanner: {scanner_id}")

            # Sync bands from config
            config_bands = payload.get('bands', [])
            for band_data in config_bands:
                Band.objects.update_or_create(
                    scanner=scanner,
                    name=band_data['name'],
                    defaults={
                        'start_hz': band_data['start_hz'],
                        'stop_hz': band_data['stop_hz'],
                        'enabled': band_data.get('enabled', True),
                    }
                )

            # Forward config to WebSocket clients
            async_to_sync(self.channel_layer.group_send)(
                'scans_all',
                {
                    'type': 'scanner_config',
                    'data': {
                        'scanner_id': scanner_id,
                        **payload,
                    },
                }
            )

        except Exception as e:
            logger.error(f"Error handling scanner config: {e}")

    def handle_status(self, scanner_id: str, payload: dict):
        """Process scanner status update."""
        logger.debug(f"Received status from {scanner_id}: {payload}")

        # Update scanner in database
        self.update_scanner_status(scanner_id, payload)

        # Forward to WebSocket clients
        async_to_sync(self.channel_layer.group_send)(
            'scans_all',
            {
                'type': 'scanner_status',
                'data': {
                    'scanner_id': scanner_id,
                    **payload,
                },
            }
        )

    def store_scan(self, scanner_id: str, payload: dict):
        """Store scan in database.

        Payload format (minimal):
        {
            "timestamp": "2025-12-09T19:30:00Z",
            "band": "UHF",
            "hz_lo": 470000000,
            "hz_hi": 608000000,
            "step": 12207.03125,
            "power": [-85.2, -82.1, ...]
        }
        """
        from core.models import Scanner, Band, Scan

        try:
            # Get or create scanner
            scanner, created = Scanner.objects.get_or_create(
                id=scanner_id,
                defaults={
                    'name': scanner_id,
                    'scanner_type': 'pluto',
                }
            )

            # Update last seen
            scanner.online = True
            scanner.last_seen = timezone.now()
            scanner.save(update_fields=['online', 'last_seen'])

            # Find band by name (band is per-scanner now)
            band = None
            band_name = payload.get('band')
            if band_name:
                band = Band.objects.filter(scanner=scanner, name=band_name).first()

            # Parse timestamp or use current time
            timestamp = timezone.now()
            if 'timestamp' in payload:
                try:
                    timestamp = datetime.fromisoformat(payload['timestamp'].replace('Z', '+00:00'))
                except (ValueError, AttributeError):
                    pass

            # Create scan record
            Scan.objects.create(
                scanner=scanner,
                band=band,
                timestamp=timestamp,
                hz_lo=int(payload['hz_lo']),
                hz_hi=int(payload['hz_hi']),
                step_hz=float(payload['step']),
                power=payload['power'],
                metadata={},
            )

        except Exception as e:
            logger.error(f"Error storing scan: {e}")

    def update_scanner_status(self, scanner_id: str, payload: dict):
        """Update scanner status in database."""
        from core.models import Scanner

        try:
            Scanner.objects.filter(id=scanner_id).update(
                online=payload.get('online', True),
                scanning=payload.get('scanning', False),
                current_band=payload.get('current_band', ''),
                last_seen=timezone.now(),
            )
        except Exception as e:
            logger.error(f"Error updating scanner status: {e}")

    def run(self):
        """Start the MQTT bridge (blocking)."""
        self.connect()
        logger.info("MQTT bridge running...")
        self.client.loop_forever()

    def stop(self):
        """Stop the MQTT bridge."""
        self.client.disconnect()
