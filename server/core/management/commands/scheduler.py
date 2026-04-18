"""
Management command that runs APScheduler for periodic background jobs.

Jobs:
- Per-scanner data rollup (every 5 minutes)
- Scanner schedule sync (every 10 minutes)
- DynSec full sync (every 10 minutes)

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


def run_dynsec_sync():
    """Full idempotent sync of dynsec state with Django DB."""
    from realtime.dynsec import DynSecClient, full_sync

    dynsec = DynSecClient()
    try:
        full_sync(dynsec)
        logger.info("DynSec periodic sync complete")
    except Exception as e:
        logger.error(f"DynSec periodic sync failed: {e}")
    finally:
        dynsec.close()


class Command(BaseCommand):
    help = "Run APScheduler for background jobs"

    def handle(self, *args, **options):
        from core.models import Scanner

        scheduler = BlockingScheduler()

        # Initial rollup schedule setup
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

        # Periodic schedule sync (pick up new/deleted scanners)
        scheduler.add_job(
            sync_schedules,
            "interval",
            minutes=SYNC_INTERVAL_MINUTES,
            id="sync-schedules",
            args=[scheduler],
            replace_existing=True,
        )

        # Periodic dynsec full sync (catches expired grants, drift)
        scheduler.add_job(
            run_dynsec_sync,
            "interval",
            minutes=SYNC_INTERVAL_MINUTES,
            id="dynsec-sync",
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
