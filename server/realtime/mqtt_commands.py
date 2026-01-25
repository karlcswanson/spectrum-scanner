"""MQTT command publisher for scanner control.

Provides a simple interface for publishing commands to scanners via MQTT.
Used by the API views to implement remote start/stop functionality.
"""

import json
import logging

import paho.mqtt.client as mqtt
from django.conf import settings

logger = logging.getLogger(__name__)


def publish_command(scanner_id: str, command: str, payload: dict = None) -> bool:
    """Publish a command to a scanner via MQTT.

    Args:
        scanner_id: UUID of the target scanner
        command: Command name (start, stop, bands, gain)
        payload: Optional JSON payload for the command

    Returns:
        True if published successfully, False otherwise
    """
    try:
        topic_prefix = getattr(settings, 'MQTT_TOPIC_PREFIX', 'spectrum')
        topic = f"{topic_prefix}/commands/{scanner_id}/{command}"

        # Create a temporary client for publishing
        client = mqtt.Client(
            client_id=f"spectrum-api-{command}",
            protocol=mqtt.MQTTv5,
        )

        # Use bridge credentials if available
        mqtt_username = getattr(settings, 'MQTT_BRIDGE_USERNAME', None)
        mqtt_password = getattr(settings, 'MQTT_BRIDGE_PASSWORD', None)
        if mqtt_username and mqtt_password:
            client.username_pw_set(mqtt_username, mqtt_password)

        # Connect, publish, disconnect
        client.connect(
            settings.MQTT_BROKER_HOST,
            settings.MQTT_BROKER_PORT,
            keepalive=10,
        )

        message = json.dumps(payload) if payload else "{}"
        result = client.publish(topic, message, qos=1)
        result.wait_for_publish(timeout=5.0)

        client.disconnect()

        logger.info(f"Published {command} command to scanner {scanner_id[:8]}...")
        return True

    except Exception as e:
        logger.error(f"Failed to publish {command} command to {scanner_id}: {e}")
        return False


def start_scanner(scanner_id: str) -> bool:
    """Send start command to a scanner."""
    return publish_command(scanner_id, 'start')


def stop_scanner(scanner_id: str) -> bool:
    """Send stop command to a scanner."""
    return publish_command(scanner_id, 'stop')


def update_bands(scanner_id: str, bands: list) -> bool:
    """Send band configuration update to a scanner.

    Args:
        scanner_id: UUID of the target scanner
        bands: List of band configs [{"name": "UHF", "enabled": true, ...}, ...]
    """
    return publish_command(scanner_id, 'bands', bands)


def update_gain(scanner_id: str, rx_gain: float, rx_gain_mode: str = None) -> bool:
    """Send gain update to a scanner.

    Args:
        scanner_id: UUID of the target scanner
        rx_gain: RX gain in dB
        rx_gain_mode: Gain mode (manual, slow_attack, fast_attack)
    """
    payload = {'rx_gain': rx_gain}
    if rx_gain_mode:
        payload['rx_gain_mode'] = rx_gain_mode
    return publish_command(scanner_id, 'gain', payload)
