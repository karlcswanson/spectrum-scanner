"""Read-path caching service for the hot history/timeline/at_time endpoints.

Everything the request path and the background pre-warmer share lives here so
the two can't drift: the same key builders, the same compute functions, and the
same TTLs. The view computes on demand; the scheduler's warm loop replays the
*exact* params real requests registered, so a warmed entry always matches the
key a browser will ask for.

Design notes:
- ``cached_or_compute`` collapses a cold-cache stampede of identical requests
  into one DB query via a Redis lock (single-flight). See ``settings.CACHES``.
- Warming is **demand-driven**, not fleet-driven: only (scanner, band, params)
  combinations that were actually requested in the last ``WARM_TTL`` seconds are
  kept warm. Cost therefore scales with concurrent *viewership*, not with the
  number of scanners — an idle scanner is warmed zero times. The warm markers
  auto-expire, so the set prunes itself with no bookkeeping.
- Only relative "hours" requests (the live-tail poll every viewer makes) are
  warmed. Absolute start/end ranges are one-off scrubs; they stay lazy-cached.
"""

import logging
from datetime import timedelta

from django.core.cache import cache
from django.utils import timezone

logger = logging.getLogger(__name__)

# Cache TTLs (seconds). History/timeline data advances ~every 10 s, so a 10 s
# TTL keeps the fan-out of identical queries off Postgres without showing
# meaningfully stale data. at_time answers are near-immutable for past
# timestamps, so a longer TTL is fine.
HISTORY_CACHE_TTL = 10
TIMELINE_CACHE_TTL = 10
AT_TIME_CACHE_TTL = 30

# A (scanner, band, params) combo stays "warm" for this long after its last
# request. Must comfortably exceed the pre-warm interval so a still-watched key
# is always refreshed before it drops out.
WARM_TTL = 30
WARM_PREFIX = 'warm:'
# Safety cap so a pathological client can't make one warm cycle unbounded.
WARM_MAX_PER_CYCLE = 500

# Sentinel so a genuinely cached ``None``/empty value is distinguishable from a
# miss (and from django-redis returning the default when Redis is unreachable).
_MISS = object()


# ── Single-flight wrapper ──────────────────────────────────────────────────

def cached_or_compute(key, ttl, compute, *, lock_timeout=20, blocking_timeout=10):
    """Return ``(data, hit)`` for ``key``, computing + caching on a miss.

    ``compute`` is a zero-arg callable returning JSON-serialisable data. On a
    miss, a single caller computes under a Redis lock (single-flight) while the
    others wait for the filled value. ``hit`` is ``True`` when the value came
    from the cache — handy for an ``X-Cache`` header.
    """
    cached = cache.get(key, _MISS)
    if cached is not _MISS:
        return cached, True

    lock = getattr(cache, 'lock', None)
    if lock is None:
        # Backend has no distributed lock (e.g. LocMem): just compute.
        data = compute()
        cache.set(key, data, ttl)
        return data, False

    try:
        with lock(f'sflock:{key}', timeout=lock_timeout, blocking_timeout=blocking_timeout):
            # Double-check: another caller may have filled it while we waited.
            cached = cache.get(key, _MISS)
            if cached is not _MISS:
                return cached, True
            data = compute()
            cache.set(key, data, ttl)
            return data, False
    except Exception:
        # Lock unavailable/contended, or a Redis hiccup: fall back to computing
        # without the single-flight guard rather than failing the request.
        cached = cache.get(key, _MISS)
        if cached is not _MISS:
            return cached, True
        data = compute()
        cache.set(key, data, ttl)
        return data, False


def bucket_epoch(dt, seconds=10):
    """Floor a datetime to a ``seconds``-wide epoch bucket for stable cache keys.

    Absolute-range and ``at_time`` requests that differ by a few hundred ms
    should share a cache entry; rounding the timestamp into a bucket makes the
    key stable without materially changing the data (scans arrive ~every 10 s).
    """
    return int(dt.timestamp()) // seconds * seconds


# ── Time-window resolution + key builders (shared by view and warmer) ──────

def resolve_hours_window(hours):
    """Relative window ending now. Key on the (rounded) window, not the exact
    now(), so requests within a TTL collapse onto one entry."""
    end = timezone.now()
    start = end - timedelta(hours=hours)
    return start, end, f'h{hours}'


def resolve_range_window(start_time, end_time):
    """Absolute window, bucketed so near-identical requests share an entry."""
    return start_time, end_time, f's{bucket_epoch(start_time)}-{bucket_epoch(end_time)}'


def resolve_capped_window(cap_seconds):
    """Fixed recent window for read-only share sessions. Every capped request
    (whatever hours/start/end it asked for) collapses onto this one key."""
    end = timezone.now()
    start = end - timedelta(seconds=cap_seconds)
    return start, end, f'c{cap_seconds}'


def resolve_window(spec):
    """Resolve a warm spec's rolling window: capped for read-only sessions,
    otherwise relative-hours. Re-evaluated each warm cycle so it stays current."""
    cap = spec.get('cap_seconds')
    if cap is not None:
        return resolve_capped_window(cap)
    return resolve_hours_window(spec['hours'])


def history_cache_key(scanner_id, band_name, range_key, limit, decimated):
    return f'hist:{scanner_id}:{band_name or ""}:{range_key}:{limit}:{int(decimated)}'


def timeline_cache_key(scanner_id, band_name, range_key):
    return f'tl:{scanner_id}:{band_name or ""}:{range_key}'


# ── Compute functions (the DB + serialize work) ────────────────────────────

def compute_history(scanner_id, band_name, start_time, end_time, limit, decimated):
    """Raw scans in the window, backfilled with the finest ScanSummary tier for
    the older range not covered by raw scans. Returns serialised rows."""
    from core.models import Scan, ScanSummary
    from .serializers import (
        DecimatedScanSerializer, DecimatedScanSummarySerializer,
        ScanSerializer, ScanSummaryAsScanSerializer,
    )

    scan_qs = Scan.objects.filter(
        scanner_id=scanner_id,
        timestamp__gte=start_time,
        timestamp__lte=end_time,
    ).order_by('timestamp')
    if band_name:
        scan_qs = scan_qs.filter(band__name=band_name)

    scans = list(scan_qs[:limit])
    raw_start = scans[0].timestamp if scans else None

    summary_qs = ScanSummary.objects.filter(
        scanner_id=scanner_id,
        bucket_start__gte=start_time,
        bucket_start__lte=end_time,
    )
    if band_name:
        summary_qs = summary_qs.filter(band__name=band_name)
    if raw_start:
        # Only backfill the range not already covered by raw scans.
        summary_qs = summary_qs.filter(bucket_start__lt=raw_start)

    finest = summary_qs.order_by('bucket_seconds').values_list('bucket_seconds', flat=True).first()
    if finest is not None:
        summary_qs = summary_qs.filter(bucket_seconds=finest).order_by('bucket_start')

    remaining = max(0, limit - len(scans))
    summaries = list(summary_qs[:remaining]) if remaining > 0 else []

    # Merge: summaries (older) + raw scans (newer).
    if decimated:
        return (
            DecimatedScanSummarySerializer(summaries, many=True).data +
            DecimatedScanSerializer(scans, many=True).data
        )
    return (
        ScanSummaryAsScanSerializer(summaries, many=True).data +
        ScanSerializer(scans, many=True).data
    )


def compute_timeline(scanner_id, band_name, start_time, end_time):
    """Scan + summary timestamps in the window (no power data), for the
    scrubber. Returns a time-sorted list of lightweight entries."""
    from core.models import Scan, ScanSummary

    scan_qs = Scan.objects.filter(
        scanner_id=scanner_id,
        timestamp__gte=start_time,
        timestamp__lte=end_time,
    ).order_by('timestamp')
    if band_name:
        scan_qs = scan_qs.filter(band__name=band_name)

    scan_entries = [
        {**s, 'source': 'raw'}
        for s in scan_qs.values('id', 'timestamp', 'band__name')
    ]

    summary_qs = ScanSummary.objects.filter(
        scanner_id=scanner_id,
        bucket_start__gte=start_time,
        bucket_start__lte=end_time,
    ).order_by('bucket_start')
    if band_name:
        summary_qs = summary_qs.filter(band__name=band_name)

    summary_entries = [
        {'id': s['id'], 'timestamp': s['bucket_start'], 'band__name': s['band__name'], 'source': 'summary'}
        for s in summary_qs.values('id', 'bucket_start', 'band__name')
    ]

    all_entries = scan_entries + summary_entries
    all_entries.sort(key=lambda x: x['timestamp'])
    return all_entries


# ── Demand-driven warm registry ────────────────────────────────────────────

def _warm_window_sig(spec):
    """Window component of the signature: capped or relative-hours."""
    cap = spec.get('cap_seconds')
    return f"c{cap}" if cap is not None else f"h{spec['hours']}"


def _warm_sig(spec):
    """Stable per-combo signature so identical requests share one warm marker."""
    win = _warm_window_sig(spec)
    if spec['kind'] == 'history':
        return (
            f"h:{spec['scanner_id']}:{spec['band'] or ''}:{win}:"
            f"{spec['limit']}:{int(spec['decimated'])}"
        )
    return f"t:{spec['scanner_id']}:{spec['band'] or ''}:{win}"


def register_warm(spec):
    """Mark a (scanner, band, params) combo as actively viewed. Cheap: one
    ``set`` with a sliding TTL. Never raises into the request path."""
    try:
        cache.set(f'{WARM_PREFIX}{_warm_sig(spec)}', spec, WARM_TTL)
    except Exception:
        pass


def _iter_warm_specs():
    """All currently-warm specs. Empty if the backend can't enumerate keys
    (LocMem / no Redis) — warming is a Redis-only optimisation."""
    iter_keys = getattr(cache, 'iter_keys', None)  # django-redis: SCAN-based
    if iter_keys is None:
        return []
    try:
        keys = list(iter_keys(f'{WARM_PREFIX}*'))
    except Exception:
        return []
    specs = []
    for key in keys:
        value = cache.get(key)
        if isinstance(value, dict):
            specs.append(value)
    return specs


def warm_spec(spec):
    """Recompute one warm spec and refill the exact cache key the matching
    request reads. Same key builders + compute as the view, so no drift."""
    start, end, range_key = resolve_window(spec)
    if spec['kind'] == 'history':
        key = history_cache_key(
            spec['scanner_id'], spec['band'], range_key,
            spec['limit'], spec['decimated'],
        )
        data = compute_history(
            spec['scanner_id'], spec['band'], start, end,
            spec['limit'], spec['decimated'],
        )
        cache.set(key, data, HISTORY_CACHE_TTL)
    else:
        key = timeline_cache_key(spec['scanner_id'], spec['band'], range_key)
        data = compute_timeline(spec['scanner_id'], spec['band'], start, end)
        cache.set(key, data, TIMELINE_CACHE_TTL)
    return key


def warm_read_cache():
    """Refresh every currently-warm history/timeline key. Called on a timer by
    the scheduler, just under the cache TTL, so watched keys are always a HIT.
    Returns the number of keys refreshed."""
    specs = _iter_warm_specs()
    if len(specs) > WARM_MAX_PER_CYCLE:
        logger.warning(
            'warm set of %d exceeds cap %d; warming only the first %d',
            len(specs), WARM_MAX_PER_CYCLE, WARM_MAX_PER_CYCLE,
        )
        specs = specs[:WARM_MAX_PER_CYCLE]

    refreshed = 0
    for spec in specs:
        try:
            warm_spec(spec)
            refreshed += 1
        except Exception as e:
            logger.warning('warm refresh failed for %s: %s', spec, e)
    return refreshed
