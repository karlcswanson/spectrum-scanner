"""Tests for retention policy parsing and aggregation helpers."""

from collections import namedtuple
from datetime import datetime, timedelta, timezone

from django.test import SimpleTestCase, TestCase
from django.utils import timezone as dj_timezone

from core import retention
from core.decimation import decimate_power
from core.models import Band, Scan, ScanSummary, Scanner


class ParseRetentionPolicyTest(SimpleTestCase):
    def test_default_policy(self):
        tiers = retention.parse_retention_policy("1s:24h,1m:7d,5m:30d,1h:1y")
        self.assertEqual(
            [t.resolution_seconds for t in tiers],
            [1, 60, 300, 3600],
        )
        self.assertEqual(
            [t.duration for t in tiers],
            [
                timedelta(days=1),
                timedelta(days=7),
                timedelta(days=30),
                timedelta(days=365),
            ],
        )

    def test_whitespace_and_empty_segments_ignored(self):
        tiers = retention.parse_retention_policy(" 1s:24h , , 1m:7d ")
        self.assertEqual(len(tiers), 2)

    def test_invalid_tier_format_raises(self):
        with self.assertRaises(ValueError):
            retention.parse_retention_policy("1s24h")   # missing colon

    def test_invalid_unit_raises(self):
        with self.assertRaises(ValueError):
            retention.parse_retention_policy("1x:24h")   # bad resolution unit


class AlignToBucketTest(SimpleTestCase):
    def test_aligns_down_to_bucket_start(self):
        dt = datetime(2026, 1, 1, 14, 3, 27, tzinfo=timezone.utc)
        aligned = retention.align_to_bucket(dt, 300)  # 5-minute bucket
        self.assertEqual(aligned, datetime(2026, 1, 1, 14, 0, 0, tzinfo=timezone.utc))

    def test_exact_boundary_unchanged(self):
        dt = datetime(2026, 1, 1, 14, 0, 0, tzinfo=timezone.utc)
        self.assertEqual(retention.align_to_bucket(dt, 300), dt)


class AggregationTest(SimpleTestCase):
    def test_elementwise_max(self):
        self.assertEqual(retention.elementwise_max([[1, 5, 3], [4, 2, 6]]), [4, 5, 6])
        self.assertEqual(retention.elementwise_max([]), [])

    def test_elementwise_mean(self):
        self.assertEqual(retention.elementwise_mean([[1, 3], [3, 5]]), [2, 4])
        self.assertEqual(retention.elementwise_mean([]), [])

    def test_weighted_mean_weights_by_scan_count(self):
        Fake = namedtuple("Fake", ["avg_power", "scan_count"])
        result, total = retention.weighted_mean([
            Fake(avg_power=[10.0, 10.0], scan_count=10),
            Fake(avg_power=[20.0, 20.0], scan_count=5),
        ])
        self.assertEqual(total, 15)
        # (10*10 + 20*5) / 15 = 13.333... per element
        for v in result:
            self.assertAlmostEqual(v, 200.0 / 15.0, places=6)

    def test_weighted_mean_empty_and_zero_count(self):
        Fake = namedtuple("Fake", ["avg_power", "scan_count"])
        self.assertEqual(retention.weighted_mean([]), ([], 0))
        self.assertEqual(
            retention.weighted_mean([Fake(avg_power=[1.0], scan_count=0)]),
            ([], 0),
        )

    def test_elementwise_drops_drastically_short_arrays(self):
        # A drastically-short outlier must not raise numpy's "inhomogeneous
        # shape"; it's dropped and the full-length sweeps aggregated.
        self.assertEqual(
            retention.elementwise_max([[1, 5, 3], [4, 2, 6], [9, 9]]), [4, 5, 6]
        )
        self.assertEqual(
            retention.elementwise_mean([[1, 3, 5], [3, 5, 7], [0, 0]]), [2, 4, 6]
        )

    def test_elementwise_truncates_near_equal_lengths(self):
        # Edge-bin jitter: a 10- and a 9-length sweep are the same grid, so both
        # are kept and truncated to the common length (no data dropped).
        result = retention.elementwise_max([[1.0] * 10, [2.0] * 9])
        self.assertEqual(len(result), 9)
        self.assertEqual(result, [2.0] * 9)

    def test_uniform_length_subset_truncates_and_drops(self):
        kept, dropped, length = retention.uniform_length_subset(
            [[1.0] * 100, [1.0] * 99, [1.0] * 5]  # 5 is drastically short
        )
        self.assertEqual(dropped, 1)
        self.assertEqual(length, 99)
        self.assertEqual([len(a) for a in kept], [99, 99])

    def test_weighted_mean_drops_off_length(self):
        Fake = namedtuple("Fake", ["avg_power", "scan_count"])
        result, total = retention.weighted_mean([
            Fake(avg_power=[10.0, 10.0], scan_count=10),
            Fake(avg_power=[20.0, 20.0], scan_count=5),
            Fake(avg_power=[1.0], scan_count=99),   # off-length -> dropped
        ])
        self.assertEqual(total, 15)  # outlier's count excluded
        for v in result:
            self.assertAlmostEqual(v, 200.0 / 15.0, places=6)


class DecimationTest(SimpleTestCase):
    def test_empty_and_passthrough(self):
        self.assertEqual(decimate_power([]), [])
        self.assertEqual(decimate_power(None), [])
        small = [1.0, 2.0, 3.0]
        self.assertEqual(decimate_power(small, target_points=1920), small)

    def test_max_pooling_matches_reference(self):
        # 10 -> 5 via max over 2-wide bins.
        self.assertEqual(decimate_power(list(range(10)), target_points=5),
                         [1, 3, 5, 7, 9])

    def test_result_length_and_peak_preserved(self):
        data = [0.0] * 100
        data[50] = 99.0  # a spike
        out = decimate_power(data, target_points=10)
        self.assertEqual(len(out), 10)
        # Max-pooling keeps the spike (it lands in the 6th bin: indices 50-59).
        self.assertEqual(max(out), 99.0)
        self.assertEqual(out[5], 99.0)


class RollupTest(TestCase):
    """Scanner.rollup() collapses raw scans past the raw-tier window into
    1-minute summaries and purges the raw rows."""

    def setUp(self):
        self.scanner = Scanner.objects.create(
            name="S",
            retention_policy="1s:24h,1m:7d,5m:30d,1h:1y",
        )
        self.band = Band.objects.create(
            scanner=self.scanner, name="UHF",
            start_hz=470_000_000, stop_hz=473_000_000,
        )

    def _make_scan(self, ts, power):
        return Scan.objects.create(
            scanner=self.scanner, band=self.band, timestamp=ts,
            hz_lo=470_000_000, hz_hi=473_000_000, step_hz=1_000_000.0,
            power=power, metadata={},
        )

    def test_raw_scans_rolled_into_minute_summary_and_purged(self):
        # Two scans in the same minute, older than the 24h raw window.
        base = retention.align_to_bucket(
            dj_timezone.now() - timedelta(hours=25), 60
        )
        self._make_scan(base, [1.0, 5.0, 3.0])
        self._make_scan(base + timedelta(seconds=30), [4.0, 2.0, 6.0])

        rolled, purged = self.scanner.rollup()

        self.assertGreaterEqual(rolled, 1)
        self.assertGreaterEqual(purged, 2)

        # Raw scans are gone.
        self.assertEqual(Scan.objects.filter(scanner=self.scanner).count(), 0)

        # One 1-minute summary with peak/avg over the two scans.
        summaries = ScanSummary.objects.filter(scanner=self.scanner, bucket_seconds=60)
        self.assertEqual(summaries.count(), 1)
        summary = summaries.first()
        self.assertEqual(summary.scan_count, 2)
        self.assertEqual(summary.peak_power, [4.0, 5.0, 6.0])
        self.assertEqual(summary.avg_power, [2.5, 3.5, 4.5])

    def test_mismatched_power_lengths_do_not_crash_rollup(self):
        # A mid-bucket geometry change leaves scans of different power lengths in
        # one bucket. Rollup must aggregate the modal-length subset (not raise)
        # and keep the summary internally consistent.
        base = retention.align_to_bucket(
            dj_timezone.now() - timedelta(hours=25), 60
        )
        self._make_scan(base, [1.0, 5.0, 3.0])
        self._make_scan(base + timedelta(seconds=20), [4.0, 2.0, 6.0])
        self._make_scan(base + timedelta(seconds=40), [9.0, 9.0])  # off-length

        rolled, purged = self.scanner.rollup()

        summaries = ScanSummary.objects.filter(scanner=self.scanner, bucket_seconds=60)
        self.assertEqual(summaries.count(), 1)
        summary = summaries.first()
        self.assertEqual(len(summary.peak_power), 3)          # modal length kept
        self.assertEqual(summary.peak_power, [4.0, 5.0, 6.0])
        self.assertEqual(summary.avg_power, [2.5, 3.5, 4.5])
        self.assertEqual(summary.scan_count, 2)               # outlier excluded

    def test_recent_scans_are_kept(self):
        # A scan within the last 24h must not be rolled up or purged.
        self._make_scan(dj_timezone.now() - timedelta(hours=1), [1.0, 2.0, 3.0])
        self.scanner.rollup()
        self.assertEqual(Scan.objects.filter(scanner=self.scanner).count(), 1)
        self.assertEqual(ScanSummary.objects.filter(scanner=self.scanner).count(), 0)
