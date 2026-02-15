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
from django.db import transaction
from django.utils import timezone

from core.models import Scanner, Scan, ScanSummary
from core.retention import (
    get_retention_tiers,
    align_to_bucket,
    elementwise_max,
    elementwise_mean,
    weighted_mean,
)


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
            rolled, purged = self._process_scanner(scanner, dry_run, batch_size)
            total_rolled_up += rolled
            total_purged += purged

        prefix = "DRY RUN: Would have " if dry_run else ""
        self.stdout.write(
            self.style.SUCCESS(
                f"{prefix}Rolled up {total_rolled_up} summaries, purged {total_purged} records"
            )
        )

    def _process_scanner(self, scanner, dry_run, batch_size):
        """Process a single scanner's retention tiers."""
        tiers = get_retention_tiers(scanner)
        now = timezone.now()

        self.stdout.write(f"Processing {scanner.name} ({len(tiers)} tiers)")

        total_rolled = 0
        total_purged = 0

        # Process tiers from coarsest to finest (skip the raw tier at index 0)
        for i in range(len(tiers) - 1, 0, -1):
            tier = tiers[i]
            source_tier = tiers[i - 1]
            bucket_seconds = tier.resolution_seconds
            source_cutoff = now - source_tier.duration

            self.stdout.write(
                f"  Tier {bucket_seconds}s: aggregating sources older than "
                f"{source_tier.duration}, keeping summaries for {tier.duration}"
            )

            if source_tier.resolution_seconds == 1:
                rolled = self._rollup_scans(
                    scanner, source_cutoff, bucket_seconds, dry_run
                )
                purged = self._purge_scans(
                    scanner, source_cutoff, dry_run, batch_size
                )
            else:
                rolled = self._rollup_summaries(
                    scanner, source_tier.resolution_seconds, source_cutoff,
                    bucket_seconds, dry_run
                )
                purged = self._purge_summaries(
                    scanner, source_tier.resolution_seconds, source_cutoff,
                    dry_run, batch_size
                )
            total_rolled += rolled
            total_purged += purged

        # Purge the coarsest tier's data beyond its keep duration
        coarsest = tiers[-1]
        coarsest_cutoff = now - coarsest.duration
        purged = self._purge_summaries(
            scanner, coarsest.resolution_seconds, coarsest_cutoff,
            dry_run, batch_size
        )
        total_purged += purged

        return total_rolled, total_purged

    def _rollup_scans(self, scanner, cutoff, bucket_seconds, dry_run):
        """Roll up raw Scan rows into ScanSummary buckets.

        Loads all eligible scans in one query, groups in Python, writes one
        transaction per band. Fast because there's no offset pagination.
        """
        scans = list(
            Scan.objects.filter(scanner=scanner, timestamp__lt=cutoff)
            .values_list('id', 'band_id', 'timestamp', 'hz_lo', 'hz_hi', 'step_hz', 'power')
            .order_by('timestamp')
        )

        if not scans:
            return 0

        self.stdout.write(f"    Rolling up {len(scans)} scans into {bucket_seconds}s buckets")

        if dry_run:
            return len(scans)

        # Group by (band_id, bucket_start)
        buckets = {}
        for _id, band_id, ts, hz_lo, hz_hi, step_hz, power in scans:
            bucket_start = align_to_bucket(ts, bucket_seconds)
            key = (band_id, bucket_start)
            if key not in buckets:
                buckets[key] = {
                    'hz_lo': hz_lo, 'hz_hi': hz_hi, 'step_hz': step_hz,
                    'power_arrays': [], 'count': 0,
                }
            buckets[key]['power_arrays'].append(power)
            buckets[key]['count'] += 1

        # Write all summaries in one transaction
        rolled = 0
        with transaction.atomic():
            for (band_id, bucket_start), data in buckets.items():
                power_arrays = [p for p in data['power_arrays'] if p]
                if not power_arrays:
                    continue

                ScanSummary.objects.update_or_create(
                    scanner=scanner,
                    band_id=band_id,
                    bucket_start=bucket_start,
                    bucket_seconds=bucket_seconds,
                    defaults={
                        'hz_lo': data['hz_lo'],
                        'hz_hi': data['hz_hi'],
                        'step_hz': data['step_hz'],
                        'peak_power': elementwise_max(power_arrays),
                        'avg_power': elementwise_mean(power_arrays),
                        'scan_count': data['count'],
                    },
                )
                rolled += 1

        self.stdout.write(f"    Created/updated {rolled} summary buckets")
        return rolled

    def _rollup_summaries(self, scanner, source_resolution, cutoff, bucket_seconds, dry_run):
        """Roll up finer ScanSummary rows into coarser buckets."""
        summaries = list(
            ScanSummary.objects.filter(
                scanner=scanner,
                bucket_seconds=source_resolution,
                bucket_start__lt=cutoff,
            )
            .order_by('bucket_start')
        )

        if not summaries:
            return 0

        self.stdout.write(
            f"    Rolling up {len(summaries)} {source_resolution}s summaries into {bucket_seconds}s buckets"
        )

        if dry_run:
            return len(summaries)

        # Group by (band_id, bucket_start)
        buckets = {}
        for s in summaries:
            bucket_start = align_to_bucket(s.bucket_start, bucket_seconds)
            key = (s.band_id, bucket_start)
            if key not in buckets:
                buckets[key] = []
            buckets[key].append(s)

        rolled = 0
        with transaction.atomic():
            for (band_id, bucket_start), items in buckets.items():
                peak_arrays = [s.peak_power for s in items if s.peak_power]
                if not peak_arrays:
                    continue

                peak = elementwise_max(peak_arrays)
                avg, total_count = weighted_mean(items)

                ref = items[0]
                ScanSummary.objects.update_or_create(
                    scanner=scanner,
                    band_id=band_id,
                    bucket_start=bucket_start,
                    bucket_seconds=bucket_seconds,
                    defaults={
                        'hz_lo': ref.hz_lo,
                        'hz_hi': ref.hz_hi,
                        'step_hz': ref.step_hz,
                        'peak_power': peak,
                        'avg_power': avg,
                        'scan_count': total_count,
                    },
                )
                rolled += 1

        self.stdout.write(f"    Created/updated {rolled} summary buckets")
        return rolled

    def _purge_scans(self, scanner, cutoff, dry_run, batch_size):
        """Delete raw Scan rows older than cutoff."""
        qs = Scan.objects.filter(scanner=scanner, timestamp__lt=cutoff)
        count = qs.count()

        if count == 0:
            return 0

        self.stdout.write(f"    Purging {count} scans older than {cutoff}")

        if dry_run:
            return count

        # Delete in batches using pk cursor (no offset scan)
        deleted_total = 0
        while True:
            batch_ids = list(qs.order_by('pk').values_list('pk', flat=True)[:batch_size])
            if not batch_ids:
                break
            with transaction.atomic():
                deleted, _ = Scan.objects.filter(pk__in=batch_ids).delete()
            deleted_total += deleted

        return deleted_total

    def _purge_summaries(self, scanner, resolution, cutoff, dry_run, batch_size):
        """Delete ScanSummary rows of a given resolution older than cutoff."""
        qs = ScanSummary.objects.filter(
            scanner=scanner,
            bucket_seconds=resolution,
            bucket_start__lt=cutoff,
        )
        count = qs.count()

        if count == 0:
            return 0

        self.stdout.write(f"    Purging {count} {resolution}s summaries older than {cutoff}")

        if dry_run:
            return count

        deleted_total = 0
        while True:
            batch_ids = list(qs.order_by('pk').values_list('pk', flat=True)[:batch_size])
            if not batch_ids:
                break
            with transaction.atomic():
                deleted, _ = ScanSummary.objects.filter(pk__in=batch_ids).delete()
            deleted_total += deleted

        return deleted_total
