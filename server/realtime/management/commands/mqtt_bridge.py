"""Django management command to run the MQTT bridge."""

import signal
import sys

from django.core.management.base import BaseCommand

from realtime.mqtt_bridge import MQTTBridge


class Command(BaseCommand):
    help = 'Run the MQTT to Django Channels bridge'

    def handle(self, *args, **options):
        self.stdout.write('Starting MQTT bridge...')

        bridge = MQTTBridge()

        def signal_handler(sig, frame):
            self.stdout.write('\nShutting down MQTT bridge...')
            bridge.stop()
            sys.exit(0)

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        try:
            bridge.run()
        except KeyboardInterrupt:
            bridge.stop()
