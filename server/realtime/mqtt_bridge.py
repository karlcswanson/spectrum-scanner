"""MQTT bridge for storing scan data to database.

This module connects to the MQTT broker and stores scan data
to the Django database for historical retrieval.

The frontend connects directly to MQTT for real-time data.

Run as a Django management command:
    python manage.py mqtt_bridge
"""

import json
import logging
import threading
from datetime import datetime

import paho.mqtt.client as mqtt
from django.core.management import call_command
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)


class MQTTBridge:
    """Bridges MQTT messages to Django database."""

    # Store scans every N seconds
    STORE_INTERVAL_SECONDS = 10

    # Rollup interval
    ROLLUP_INTERVAL_SECONDS = 300  # 5 minutes

    def __init__(self):
        self.client = mqtt.Client(
            client_id=settings.MQTT_CLIENT_ID,
            protocol=mqtt.MQTTv5,
        )
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        self.client.on_disconnect = self.on_disconnect

        # Set credentials for MQTT auth
        mqtt_username = getattr(settings, 'MQTT_BRIDGE_USERNAME', None)
        mqtt_password = getattr(settings, 'MQTT_BRIDGE_PASSWORD', None)
        if mqtt_username and mqtt_password:
            self.client.username_pw_set(mqtt_username, mqtt_password)
            logger.info(f"MQTT bridge using credentials for {mqtt_username[:8]}...")

        self.topic_prefix = settings.MQTT_TOPIC_PREFIX

        # Track last store time per scanner/band
        # Key: (scanner_id, band_name), Value: last_store_time
        self.last_store_times = {}

        # Rollup thread
        self._rollup_stop = threading.Event()

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
        """Process incoming scan data - store to database (rate limited)."""
        logger.debug(f"Received scan from {scanner_id}")

        # Check if we should store this scan (rate limited to every minute)
        band_name = payload.get('band', 'default')
        store_key = (scanner_id, band_name)
        now = timezone.now()

        should_store = False
        if store_key not in self.last_store_times:
            # First scan for this scanner/band - store it
            should_store = True
        else:
            # Check if enough time has passed since last store
            elapsed = (now - self.last_store_times[store_key]).total_seconds()
            if elapsed >= self.STORE_INTERVAL_SECONDS:
                should_store = True

        if should_store:
            self.store_scan(scanner_id, payload)
            self.last_store_times[store_key] = now
            logger.info(f"Stored scan for {scanner_id}/{band_name}")

    def handle_config(self, scanner_id: str, payload: dict):
        """Process scanner config update - sync to database.

        Scanner must already exist in DB (created via Django admin).
        This updates the scanner's bands and status from the config message.
        """
        from core.models import Scanner, Band

        try:
            logger.info(f"Received config from {scanner_id[:8]}...: {payload.get('name')}")

            # Scanner must already exist (created in Django admin)
            try:
                scanner = Scanner.objects.get(id=scanner_id)
            except Scanner.DoesNotExist:
                logger.warning(f"Received config from unknown scanner {scanner_id[:8]}... - ignoring")
                return

            # Update scanner status
            scanner.online = True
            scanner.last_seen = timezone.now()
            # Optionally update name/location from config if empty in DB
            if not scanner.name:
                scanner.name = payload.get('name', scanner_id[:8])
            if not scanner.location:
                scanner.location = payload.get('location', '')
            scanner.save()

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

        except Exception as e:
            logger.error(f"Error handling scanner config: {e}")

    def handle_status(self, scanner_id: str, payload: dict):
        """Process scanner status update - update database."""
        logger.debug(f"Received status from {scanner_id}: {payload}")
        self.update_scanner_status(scanner_id, payload)

    def store_scan(self, scanner_id: str, payload: dict):
        """Store scan in database.

        Scanner must already exist in DB (created via Django admin).
        """
        from core.models import Scanner, Band, Scan

        try:
            # Scanner must already exist (created in Django admin)
            try:
                scanner = Scanner.objects.get(id=scanner_id)
            except Scanner.DoesNotExist:
                logger.debug(f"Ignoring scan from unknown scanner {scanner_id[:8]}...")
                return

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
            scan = Scan.objects.create(
                scanner=scanner,
                band=band,
                timestamp=timestamp,
                hz_lo=int(payload['hz_lo']),
                hz_hi=int(payload['hz_hi']),
                step_hz=float(payload['step']),
                power=payload['power'],
                metadata={},
            )

            # Publish timeline update so frontend scrubbers can update
            self.publish_timeline_update(scanner_id, scan, band_name)

        except Exception as e:
            logger.error(f"Error storing scan: {e}")

    def publish_timeline_update(self, scanner_id: str, scan, band_name: str):
        """Publish a timeline update notification to MQTT.

        This tells the frontend that a new scan was stored in the database,
        so the time scrubber can add a new marker without polling.
        Includes full scan data so frontend can add to cache without API call.
        """
        try:
            timeline_topic = f"{self.topic_prefix}/scanners/{scanner_id}/timeline"
            timeline_data = {
                'id': scan.id,
                'timestamp': scan.timestamp.isoformat(),
                'band__name': band_name,
                # Include full scan data for caching
                'scan': {
                    'hz_lo': scan.hz_lo,
                    'hz_hi': scan.hz_hi,
                    'step_hz': scan.step_hz,
                    'power': scan.power,
                }
            }
            self.client.publish(
                timeline_topic,
                json.dumps(timeline_data),
                qos=0,  # Fire and forget - not critical
            )
            logger.debug(f"Published timeline update for {scanner_id}/{band_name}")
        except Exception as e:
            logger.error(f"Error publishing timeline update: {e}")

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

    def _rollup_loop(self):
        """Background thread that runs rollup periodically."""
        logger.info(f"Rollup thread started (every {self.ROLLUP_INTERVAL_SECONDS}s)")
        while not self._rollup_stop.wait(self.ROLLUP_INTERVAL_SECONDS):
            try:
                logger.info("Running scheduled rollup...")
                call_command('rollup')
                logger.info("Rollup completed")
            except Exception as e:
                logger.error(f"Rollup failed: {e}")

    def run(self):
        """Start the MQTT bridge (blocking)."""
        self._rollup_stop.clear()
        rollup_thread = threading.Thread(target=self._rollup_loop, daemon=True)
        rollup_thread.start()

        self.connect()
        logger.info("MQTT bridge running...")
        self.client.loop_forever()

    def stop(self):
        """Stop the MQTT bridge."""
        self._rollup_stop.set()
        self.client.disconnect()
