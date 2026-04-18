"""Django management command to run the MQTT bridge."""

import signal
import sys
import time

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

        # Retry connection on startup — the bridge client may not be
        # provisioned in dynsec yet if dynsec_sync hasn't run.
        max_retries = 10
        for attempt in range(1, max_retries + 1):
            try:
                bridge.run()
                break
            except KeyboardInterrupt:
                bridge.stop()
                break
            except Exception as e:
                if attempt < max_retries:
                    wait = min(attempt * 2, 10)
                    self.stderr.write(f'MQTT bridge connect failed ({e}), retrying in {wait}s...')
                    time.sleep(wait)
                    bridge = MQTTBridge()
                else:
                    self.stderr.write(f'MQTT bridge failed after {max_retries} attempts: {e}')
                    sys.exit(1)
