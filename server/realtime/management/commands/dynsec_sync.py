"""Full idempotent sync of Mosquitto Dynamic Security state with Django DB.

Run on every deploy (part of server entrypoint) or manually to recover
from desync.

Usage:
    python manage.py dynsec_sync
    python manage.py dynsec_sync --force   # also deletes orphaned dynsec clients
"""

import logging

from django.conf import settings
from django.core.management.base import BaseCommand

from core.models import Scanner, UserMQTTCredentials
from realtime.dynsec import DynSecClient, full_sync

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Synchronise Mosquitto Dynamic Security state with Django DB'

    def add_arguments(self, parser):
        parser.add_argument(
            '--force',
            action='store_true',
            help='Delete orphaned dynsec clients not in Django DB',
        )

    def handle(self, *args, **options):
        dynsec = DynSecClient()
        try:
            full_sync(dynsec)
            self.stdout.write(self.style.SUCCESS('DynSec sync complete.'))

            if options['force']:
                self._cleanup_orphans(dynsec)
        finally:
            dynsec.close()

    def _cleanup_orphans(self, dynsec: DynSecClient):
        """Delete dynsec clients that don't correspond to Django objects."""
        dynsec_clients = dynsec.list_clients()
        known_usernames = {
            settings.MQTT_DYNSEC_USERNAME,
            settings.MQTT_BRIDGE_USERNAME,
        }
        known_usernames.update(
            str(s.id) for s in Scanner.objects.all()
        )
        known_usernames.update(
            str(c.mqtt_id) for c in UserMQTTCredentials.objects.all()
        )

        for client_entry in dynsec_clients:
            username = client_entry if isinstance(client_entry, str) else client_entry.get('username', '')
            if username and username not in known_usernames:
                dynsec.delete_client(username)
                self.stdout.write(self.style.WARNING(f'  deleted orphan: {username}'))
