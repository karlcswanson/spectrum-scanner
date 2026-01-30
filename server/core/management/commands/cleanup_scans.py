"""
Management command to delete old scans from the database.
Run periodically via cron or Docker healthcheck.

Usage:
    python manage.py cleanup_scans --hours 6
    python manage.py cleanup_scans --hours 6 --batch-size 5000
"""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import Scan


class Command(BaseCommand):
    help = "Delete scans older than specified hours"

    def add_arguments(self, parser):
        parser.add_argument(
            "--hours",
            type=int,
            default=6,
            help="Delete scans older than this many hours (default: 6)",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=5000,
            help="Delete in batches of this size to avoid locking (default: 5000)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be deleted without actually deleting",
        )

    def handle(self, *args, **options):
        hours = options["hours"]
        batch_size = options["batch_size"]
        dry_run = options["dry_run"]

        cutoff = timezone.now() - timedelta(hours=hours)

        # Count total to delete
        total_count = Scan.objects.filter(timestamp__lt=cutoff).count()

        if total_count == 0:
            self.stdout.write(self.style.SUCCESS(f"No scans older than {hours} hours"))
            return

        if dry_run:
            self.stdout.write(
                self.style.WARNING(f"DRY RUN: Would delete {total_count} scans older than {hours} hours")
            )
            return

        self.stdout.write(f"Deleting {total_count} scans older than {hours} hours...")

        deleted_total = 0
        while True:
            # Get batch of IDs to delete (avoids loading full objects)
            ids_to_delete = list(
                Scan.objects.filter(timestamp__lt=cutoff)
                .values_list("id", flat=True)[:batch_size]
            )

            if not ids_to_delete:
                break

            # Delete batch
            deleted_count, _ = Scan.objects.filter(id__in=ids_to_delete).delete()
            deleted_total += deleted_count
            self.stdout.write(f"  Deleted {deleted_total}/{total_count}...")

        self.stdout.write(
            self.style.SUCCESS(f"Deleted {deleted_total} scans older than {hours} hours")
        )
