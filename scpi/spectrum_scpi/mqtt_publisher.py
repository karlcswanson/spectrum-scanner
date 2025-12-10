"""MQTT publisher for scan data."""

import json
import logging
from datetime import datetime

import paho.mqtt.client as mqtt

from .analyzer import ScanResult

logger = logging.getLogger(__name__)


class MQTTPublisher:
    """Publishes scan data to MQTT broker."""

    def __init__(
        self,
        broker_host: str = "localhost",
        broker_port: int = 1883,
        scanner_id: str = "scpi-scanner",
        scanner_name: str = "SCPI Scanner",
        scanner_type: str = "scpi-generic",
        location: str = "",
    ):
        self.broker_host = broker_host
        self.broker_port = broker_port
        self.scanner_id = scanner_id
        self.scanner_name = scanner_name
        self.scanner_type = scanner_type
        self.location = location

        self.client = mqtt.Client(
            client_id=f"spectrum-scpi-{scanner_id}",
            protocol=mqtt.MQTTv5,
        )
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect

        self.connected = False
        self.topic_prefix = "spectrum"

    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        if reason_code == 0:
            logger.info(f"Connected to MQTT broker at {self.broker_host}:{self.broker_port}")
            self.connected = True
            # Publish online status
            self._publish_status(online=True, scanning=False)
        else:
            logger.error(f"Failed to connect to MQTT: {reason_code}")

    def _on_disconnect(self, client, userdata, reason_code, properties=None):
        logger.warning(f"Disconnected from MQTT broker: {reason_code}")
        self.connected = False

    def connect(self) -> None:
        """Connect to MQTT broker."""
        logger.info(f"Connecting to MQTT broker at {self.broker_host}:{self.broker_port}")
        self.client.connect(self.broker_host, self.broker_port, keepalive=60)
        self.client.loop_start()

    def disconnect(self) -> None:
        """Disconnect from MQTT broker."""
        self._publish_status(online=False, scanning=False)
        self.client.loop_stop()
        self.client.disconnect()

    def _publish_status(self, online: bool, scanning: bool, current_band: str = "") -> None:
        """Publish scanner status."""
        topic = f"{self.topic_prefix}/scanners/{self.scanner_id}/status"
        payload = {
            "online": online,
            "scanning": scanning,
            "current_band": current_band,
        }
        self.client.publish(topic, json.dumps(payload), qos=1, retain=True)

    def publish_scan(self, scan: ScanResult) -> None:
        """Publish a scan result to MQTT."""
        topic = f"{self.topic_prefix}/scanners/{self.scanner_id}/scan"

        payload = {
            "source": {
                "id": self.scanner_id,
                "name": self.scanner_name,
                "type": self.scanner_type,
                "location": self.location,
            },
            "scan": {
                "timestamp": scan.timestamp.isoformat(),
                "band": scan.band,
                "hz_lo": scan.hz_lo,
                "hz_hi": scan.hz_hi,
                "step": scan.step_hz,
                "power": scan.power,
            },
            "metadata": {
                "rbw_hz": scan.rbw_hz,
            },
        }

        self.client.publish(topic, json.dumps(payload), qos=0)
        logger.debug(f"Published scan to {topic}")

    def set_scanning(self, scanning: bool, band: str = "") -> None:
        """Update scanning status."""
        self._publish_status(online=True, scanning=scanning, current_band=band)
