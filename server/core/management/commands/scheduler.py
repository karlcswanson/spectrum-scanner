"""
Management command that runs APScheduler for periodic background jobs.

Jobs:
- Per-scanner data rollup (every 5 minutes)
- Scanner schedule sync (every 10 minutes)
- DynSec full sync (every 10 minutes)
- Expired-session cleanup (every 60 minutes)

Usage:
    python manage.py scheduler
"""

import logging

from apscheduler.schedulers.blocking import BlockingScheduler
from django.core.management.base import BaseCommand
from django.db import close_old_connections

logger = logging.getLogger(__name__)

ROLLUP_INTERVAL_MINUTES = 5
SYNC_INTERVAL_MINUTES = 10
CLEARSESSIONS_INTERVAL_MINUTES = 60
# Just under the 10 s read-cache TTL so actively-viewed history/timeline keys
# are always refreshed before they expire (viewers stay a cache HIT).
WARM_INTERVAL_SECONDS = 8


def run_rollup(scanner_id: str):
    """Run rollup for a single scanner."""
    from core.models import Scanner

    # No request cycle here to recycle DB connections, so a Postgres restart or
    # idle drop leaves a dead connection that fails every subsequent run. Refresh
    # stale/closed connections before touching the ORM.
    close_old_connections()
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

    close_old_connections()
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


def run_clearsessions():
    """Delete expired django_session rows.

    Share-link visitors each create a session row; without cleanup the table
    grows unbounded (especially under a public link + link-preview bots).
    """
    from django.core.management import call_command

    close_old_connections()
    try:
        call_command("clearsessions")
        logger.info("Cleared expired sessions")
    except Exception as e:
        logger.error(f"clearsessions failed: {e}")


def run_warm_read_cache():
    """Keep actively-viewed history/timeline cache keys warm.

    Demand-driven: only (scanner, band, params) combos requested in the last
    ~30 s are refreshed, so cost scales with concurrent viewership, not fleet
    size. Idle scanners are warmed zero times. No-ops without Redis.
    """
    from api.cache import warm_read_cache

    close_old_connections()
    try:
        refreshed = warm_read_cache()
        if refreshed:
            logger.debug(f"Warmed {refreshed} read-cache key(s)")
    except Exception as e:
        logger.error(f"Read-cache warm failed: {e}")


def run_dynsec_sync():
    """Full idempotent sync of dynsec state with Django DB."""
    from realtime.dynsec import DynSecClient, full_sync

    close_old_connections()
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

        # Periodic expired-session cleanup
        scheduler.add_job(
            run_clearsessions,
            "interval",
            minutes=CLEARSESSIONS_INTERVAL_MINUTES,
            id="clearsessions",
            replace_existing=True,
        )

        # Keep actively-viewed read-cache keys warm (public-demo scaling).
        # coalesce + max_instances=1 so a slow cycle can't pile up.
        scheduler.add_job(
            run_warm_read_cache,
            "interval",
            seconds=WARM_INTERVAL_SECONDS,
            id="warm-read-cache",
            replace_existing=True,
            coalesce=True,
            max_instances=1,
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"Scheduler started: {scanners.count()} scanner(s), "
                f"rollup every {ROLLUP_INTERVAL_MINUTES}m, "
                f"sync every {SYNC_INTERVAL_MINUTES}m"
            )
        )

        scheduler.start()
