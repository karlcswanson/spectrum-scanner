"""
Management command that runs APScheduler for per-scanner rollup jobs.

Schedules are built from the Scanner table on startup — no extra persistence
needed. A sync job periodically adds/removes schedules for new/deleted scanners.

Usage:
    python manage.py scheduler
"""

import logging

from apscheduler.schedulers.blocking import BlockingScheduler
from django.core.management.base import BaseCommand

logger = logging.getLogger(__name__)

ROLLUP_INTERVAL_MINUTES = 5
SYNC_INTERVAL_MINUTES = 10


def run_rollup(scanner_id: str):
    """Run rollup for a single scanner."""
    from core.models import Scanner

    try:
        scanner = Scanner.objects.get(id=scanner_id)
    except Scanner.DoesNotExist:
        logger.warning(f"Scanner {scanner_id} not found, skipping rollup")
        return

    rolled, purged = scanner.rollup()
    if rolled or purged:
        logger.info(f"Rollup {scanner.name}: {rolled} summaries, {purged} purged")


def sync_schedules(scheduler: BlockingScheduler):
    """Add/remove rollup schedules to match current Scanner table."""
    from core.models import Scanner

    scanner_ids = set(
        str(sid) for sid in Scanner.objects.values_list("id", flat=True)
    )
    expected_ids = {f"rollup-{sid}" for sid in scanner_ids}

    # Current job IDs managed by us
    current_ids = {
        job.id for job in scheduler.get_jobs()
        if job.id.startswith("rollup-")
    }

    # Remove jobs for deleted scanners
    for job_id in current_ids - expected_ids:
        logger.info(f"Removing job {job_id} (scanner deleted)")
        scheduler.remove_job(job_id)

    # Add jobs for new scanners
    for scanner_id in scanner_ids:
        job_id = f"rollup-{scanner_id}"
        if job_id not in current_ids:
            logger.info(f"Adding job {job_id}")
            scheduler.add_job(
                run_rollup,
                "interval",
                minutes=ROLLUP_INTERVAL_MINUTES,
                id=job_id,
                args=[scanner_id],
                replace_existing=True,
            )


class Command(BaseCommand):
    help = "Run APScheduler for per-scanner rollup jobs"

    def handle(self, *args, **options):
        from core.models import Scanner

        scheduler = BlockingScheduler()

        # Initial schedule setup
        scanners = Scanner.objects.all()
        for scanner in scanners:
            job_id = f"rollup-{scanner.id}"
            logger.info(f"Scheduling {job_id} ({scanner.name})")
            scheduler.add_job(
                run_rollup,
                "interval",
                minutes=ROLLUP_INTERVAL_MINUTES,
                id=job_id,
                args=[str(scanner.id)],
                replace_existing=True,
            )

        # Sync job to pick up new/deleted scanners
        scheduler.add_job(
            sync_schedules,
            "interval",
            minutes=SYNC_INTERVAL_MINUTES,
            id="sync-schedules",
            args=[scheduler],
            replace_existing=True,
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"Scheduler started: {scanners.count()} scanner(s), "
                f"rollup every {ROLLUP_INTERVAL_MINUTES}m, "
                f"sync every {SYNC_INTERVAL_MINUTES}m"
            )
        )

        scheduler.start()
