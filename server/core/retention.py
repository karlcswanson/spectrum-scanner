"""TSDB-style retention policy parsing and aggregation utilities.

Retention policies use Graphite/Whisper-style format:
    "1s:24h,1m:7d,5m:30d,1h:1y"

Read as: keep raw scans 24h, 1-min summaries 7d, 5-min summaries 30d, 1-hour summaries 1y.
"""

import re
from collections import namedtuple
from datetime import datetime, timedelta

import numpy as np

DEFAULT_RETENTION_POLICY = "1s:24h,1m:7d,5m:30d,1h:1y"

RetentionTier = namedtuple("RetentionTier", ["resolution_seconds", "duration"])

# Duration unit multipliers
DURATION_UNITS = {
    "s": 1,
    "m": 60,
    "h": 3600,
    "d": 86400,
    "w": 604800,
    "y": 365 * 86400,
}


def _parse_duration(s):
    """Parse a duration string like '24h', '7d', '1y' into a timedelta."""
    match = re.match(r"^(\d+)([smhdwy])$", s.strip())
    if not match:
        raise ValueError(f"Invalid duration: {s!r}")
    value = int(match.group(1))
    unit = match.group(2)
    return timedelta(seconds=value * DURATION_UNITS[unit])


def _parse_resolution(s):
    """Parse a resolution string like '1s', '1m', '5m' into seconds."""
    match = re.match(r"^(\d+)([smhdwy])$", s.strip())
    if not match:
        raise ValueError(f"Invalid resolution: {s!r}")
    value = int(match.group(1))
    unit = match.group(2)
    return value * DURATION_UNITS[unit]


def parse_retention_policy(policy_str):
    """Parse a Graphite-style retention policy string into a list of RetentionTiers.

    Example:
        >>> parse_retention_policy("1s:24h,1m:7d,5m:30d,1h:1y")
        [RetentionTier(resolution_seconds=1, duration=timedelta(days=1)),
         RetentionTier(resolution_seconds=60, duration=timedelta(days=7)),
         ...]
    """
    tiers = []
    for tier_str in policy_str.split(","):
        tier_str = tier_str.strip()
        if not tier_str:
            continue
        parts = tier_str.split(":")
        if len(parts) != 2:
            raise ValueError(f"Invalid tier format: {tier_str!r} (expected 'resolution:duration')")
        resolution_seconds = _parse_resolution(parts[0])
        duration = _parse_duration(parts[1])
        tiers.append(RetentionTier(resolution_seconds=resolution_seconds, duration=duration))
    return tiers


def resolve_retention_policy(scanner):
    """Resolve the effective retention policy for a scanner.

    Priority: scanner.retention_policy > SiteSettings global > DEFAULT_RETENTION_POLICY
    """
    # Scanner-level override
    if scanner.retention_policy:
        return scanner.retention_policy

    # Global SiteSettings default
    from core.models import SiteSettings

    global_policy = SiteSettings.get("retention_policy")
    if global_policy:
        return global_policy

    return DEFAULT_RETENTION_POLICY


def get_retention_tiers(scanner):
    """Get parsed retention tiers for a scanner."""
    policy_str = resolve_retention_policy(scanner)
    return parse_retention_policy(policy_str)


def align_to_bucket(dt, bucket_seconds):
    """Align a datetime to the start of its bucket.

    Example: align_to_bucket(14:03:27, 300) -> 14:00:00
    """
    timestamp = dt.timestamp()
    aligned = (timestamp // bucket_seconds) * bucket_seconds
    return datetime.fromtimestamp(aligned, tz=dt.tzinfo)


# Sweeps whose length is at least this fraction of the longest in a bucket are
# treated as the same frequency grid with edge-bin jitter: they're truncated to
# a common length and all kept. Shorter arrays (a failed/partial sweep or a real
# resolution change) are dropped so they can't chop the whole bucket down to
# their length. Observed jitter on real hardware is <1%; a genuine resolution
# change is a large step, so 0.9 separates them cleanly.
SWEEP_LENGTH_TOLERANCE = 0.9


def uniform_length_subset(arrays):
    """Return ``(kept, dropped_count, length)`` for element-wise aggregation.

    Non-empty arrays within ``SWEEP_LENGTH_TOLERANCE`` of the longest are kept
    and truncated to their common (minimum) length so they share one bin grid;
    drastically shorter arrays are dropped. This both avoids numpy's
    "inhomogeneous shape" error and, unlike dropping every off-length array,
    retains the near-full sweeps that only differ by a few edge bins — important
    so rolled-up peaks don't miss transients.
    """
    arrays = [a for a in arrays if a]
    if not arrays:
        return [], 0, 0
    longest = max(len(a) for a in arrays)
    threshold = longest * SWEEP_LENGTH_TOLERANCE
    kept = [a for a in arrays if len(a) >= threshold]
    target = min(len(a) for a in kept)
    truncated = [a[:target] for a in kept]
    return truncated, len(arrays) - len(kept), target


def elementwise_max(arrays):
    """Element-wise maximum across arrays (truncated to a common length)."""
    kept, _, _ = uniform_length_subset(arrays)
    if not kept:
        return []
    return np.array(kept, dtype=np.float64).max(axis=0).tolist()


def elementwise_mean(arrays):
    """Element-wise mean across arrays (truncated to a common length)."""
    kept, _, _ = uniform_length_subset(arrays)
    if not kept:
        return []
    return np.array(kept, dtype=np.float64).mean(axis=0).tolist()


def weighted_mean(summaries):
    """Compute weighted average of avg_power arrays from ScanSummary objects.

    Each summary's avg_power is weighted by its scan_count, so merging
    two summaries (one with 10 scans, one with 5) correctly weights the average.
    Arrays are truncated to a common length (drastically short ones dropped) the
    same way as ``uniform_length_subset`` so mismatched grids never crash.
    """
    summaries = [s for s in summaries if s.avg_power]
    if not summaries:
        return [], 0

    longest = max(len(s.avg_power) for s in summaries)
    threshold = longest * SWEEP_LENGTH_TOLERANCE
    kept = [s for s in summaries if len(s.avg_power) >= threshold]
    target = min(len(s.avg_power) for s in kept)

    total_count = sum(s.scan_count for s in kept)
    if total_count == 0:
        return [], 0

    weights = np.array([s.scan_count / total_count for s in kept], dtype=np.float64)
    stacked = np.array([s.avg_power[:target] for s in kept], dtype=np.float64)
    result = (stacked * weights[:, np.newaxis]).sum(axis=0)

    return result.tolist(), total_count
