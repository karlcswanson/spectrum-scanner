"""
Management command for TSDB-style scan data rollup.

Aggregates raw scans into pre-computed ScanSummary rows (peak/average),
then purges expired source data according to the retention policy.

Usage:
    python manage.py rollup
    python manage.py rollup --scanner <uuid>
    python manage.py rollup --dry-run
    python manage.py rollup --batch-size 500
"""

from django.core.management.base import BaseCommand

from core.models import Scanner


class Command(BaseCommand):
    help = "Roll up scan data into time-bucketed summaries and purge expired data"

    def add_arguments(self, parser):
        parser.add_argument(
            "--scanner",
            type=str,
            default=None,
            help="Only process this scanner UUID",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be rolled up/purged without making changes",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=500,
            help="Delete in batches of this size (default: 500)",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        batch_size = options["batch_size"]
        scanner_id = options["scanner"]

        if scanner_id:
            scanners = Scanner.objects.filter(id=scanner_id)
        else:
            scanners = Scanner.objects.all()

        if not scanners.exists():
            self.stdout.write(self.style.WARNING("No scanners found"))
            return

        total_rolled_up = 0
        total_purged = 0

        for scanner in scanners:
            self.stdout.write(f"Processing {scanner.name}")
            rolled, purged = scanner.rollup(
                dry_run=dry_run,
                batch_size=batch_size,
            )
            total_rolled_up += rolled
            total_purged += purged

        prefix = "DRY RUN: Would have " if dry_run else ""
        self.stdout.write(
            self.style.SUCCESS(
                f"{prefix}Rolled up {total_rolled_up} summaries, purged {total_purged} records"
            )
        )
