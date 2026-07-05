"""Power-array decimation for wire/preview transport.

Decimation is wire/presentation only — the DB always stores full resolution.
Full res is required for the live view, exports, and saved scans; only the
scrubber/history preview and the timeline push may be decimated (~1920 points).
Max-pooling is used so peaks (the thing operators care about) survive.
"""

import numpy as np

# Scrubber/preview target width. Matches the frontend's decimated-cache
# expectations; arrays already at or below this are passed through untouched.
DEFAULT_TARGET_POINTS = 1920


def decimate_power(power, target_points=DEFAULT_TARGET_POINTS):
    """Max-pool ``power`` down to ~``target_points``, preserving peaks.

    Returns the input unchanged when it is empty or already within the target.
    Vectorised with ``np.maximum.reduceat`` — the max over every bin is computed
    in one C-level pass rather than a Python loop, which matters because this
    runs on every timeline push and up to thousands of times per decimated
    history request.
    """
    if not power:
        return []
    n = len(power)
    if n <= target_points:
        return power

    arr = np.asarray(power, dtype=np.float64)
    factor = n / target_points
    # Bin start indices; for factor > 1 they're strictly increasing, so each
    # reduceat segment [starts[i], starts[i+1]) is a non-empty bin (the last
    # runs to the end of the array).
    starts = (np.arange(target_points) * factor).astype(np.intp)
    pooled = np.maximum.reduceat(arr, starts)
    return pooled.tolist()
