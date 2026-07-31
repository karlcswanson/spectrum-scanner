"""Core models for Spectrum Server."""

import logging
import secrets
import uuid

from django.db import models, transaction
from django.db.models import Count, Q
from django.utils import timezone

logger = logging.getLogger(__name__)


def generate_auth_token():
    """Generate a secure random token for scanner authentication."""
    return secrets.token_urlsafe(32)


class Scanner(models.Model):
    """A spectrum scanner device (Pluto, SCPI analyzer, etc.)."""

    SCANNER_TYPES = [
        ('pluto', 'ADALM-Pluto'),
        ('scpi-tti', 'TTi PSA Series'),
        ('scpi-owon', 'OWON XSA/HSA Series'),
        ('scpi-generic', 'Generic SCPI'),
        ('import', 'Imported Scan'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200)
    scanner_type = models.CharField(max_length=20, choices=SCANNER_TYPES, default='pluto')
    location = models.CharField(max_length=200, blank=True)
    description = models.TextField(blank=True)
    retention_policy = models.CharField(
        max_length=200, blank=True, default='',
        help_text='Graphite-style retention policy override (e.g. "1s:24h,1m:7d,5m:30d,1h:1y"). Empty = use global default.'
    )

    # Scanner groups (M2M - scanners can belong to multiple groups)
    scanner_groups = models.ManyToManyField(
        'ScannerGroup',
        blank=True,
        related_name='scanners'
    )

    # Authentication
    auth_token = models.CharField(max_length=64, default=generate_auth_token)
    enabled = models.BooleanField(default=True, help_text="Disabled scanners cannot connect")

    # Status (updated via MQTT)
    online = models.BooleanField(default=False)
    scanning = models.BooleanField(default=False)
    current_band = models.CharField(max_length=100, blank=True)
    last_seen = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.scanner_type})"

    def regenerate_token(self):
        """Generate a new auth token for this scanner."""
        self.auth_token = generate_auth_token()
        self.save(update_fields=['auth_token'])

    def rollup(self, dry_run=False, batch_size=500):
        """Roll up scan data into time-bucketed summaries and purge expired data.

        Returns (rolled_count, purged_count) tuple.
        """
        from core.retention import (
            get_retention_tiers,
            align_to_bucket,
            elementwise_max,
            elementwise_mean,
            weighted_mean,
        )

        tiers = get_retention_tiers(self)
        now = timezone.now()

        total_rolled = 0
        total_purged = 0

        # Process tiers from coarsest to finest (skip the raw tier at index 0)
        for i in range(len(tiers) - 1, 0, -1):
            tier = tiers[i]
            source_tier = tiers[i - 1]
            bucket_seconds = tier.resolution_seconds
            source_cutoff = now - source_tier.duration

            if source_tier.resolution_seconds == 1:
                rolled = self._rollup_scans(
                    source_cutoff, bucket_seconds, dry_run,
                    align_to_bucket, elementwise_max, elementwise_mean,
                )
                purged = self._purge_scans(source_cutoff, dry_run, batch_size)
            else:
                rolled = self._rollup_summaries(
                    source_tier.resolution_seconds, source_cutoff,
                    bucket_seconds, dry_run,
                    align_to_bucket, elementwise_max, weighted_mean,
                )
                purged = self._purge_summaries(
                    source_tier.resolution_seconds, source_cutoff,
                    dry_run, batch_size,
                )
            total_rolled += rolled
            total_purged += purged

        # Purge the coarsest tier's data beyond its keep duration
        coarsest = tiers[-1]
        coarsest_cutoff = now - coarsest.duration
        total_purged += self._purge_summaries(
            coarsest.resolution_seconds, coarsest_cutoff, dry_run, batch_size,
        )

        return total_rolled, total_purged

    def _rollup_scans(self, cutoff, bucket_seconds, dry_run,
                      align_to_bucket, elementwise_max, elementwise_mean):
        """Roll up raw Scan rows into ScanSummary buckets."""
        scans = list(
            Scan.objects.filter(scanner=self, timestamp__lt=cutoff)
            .values_list('id', 'band_id', 'timestamp', 'hz_lo', 'hz_hi', 'step_hz', 'power')
            .order_by('timestamp')
        )

        if not scans:
            return 0

        if dry_run:
            return len(scans)

        # Group by (band_id, bucket_start), keeping each scan's geometry so the
        # emitted summary's hz/step matches the arrays actually aggregated.
        buckets = {}
        for _id, band_id, ts, hz_lo, hz_hi, step_hz, power in scans:
            bucket_start = align_to_bucket(ts, bucket_seconds)
            key = (band_id, bucket_start)
            buckets.setdefault(key, []).append((power, hz_lo, hz_hi, step_hz))

        from core.retention import uniform_length_subset

        rolled = 0
        with transaction.atomic():
            for (band_id, bucket_start), entries in buckets.items():
                entries = [e for e in entries if e[0]]  # non-empty power
                if not entries:
                    continue

                # Truncate near-equal sweeps to a common bin grid; drop only
                # drastically-short (failed/reconfigured) sweeps.
                power_arrays, dropped, target = uniform_length_subset(
                    [e[0] for e in entries]
                )
                if not power_arrays:
                    continue
                if dropped:
                    logger.warning(
                        "rollup %s band %s %s: dropped %d short sweep(s); kept %d "
                        "at length %d",
                        self.id, band_id, bucket_start.isoformat(),
                        dropped, len(power_arrays), target,
                    )

                # Geometry from a kept sweep at the common length, so the stored
                # hz/step match the aggregated array length.
                geom = next((e for e in entries if len(e[0]) == target), entries[0])
                _, hz_lo, hz_hi, step_hz = geom

                ScanSummary.objects.update_or_create(
                    scanner=self,
                    band_id=band_id,
                    bucket_start=bucket_start,
                    bucket_seconds=bucket_seconds,
                    defaults={
                        'hz_lo': hz_lo,
                        'hz_hi': hz_hi,
                        'step_hz': step_hz,
                        'peak_power': elementwise_max(power_arrays),
                        'avg_power': elementwise_mean(power_arrays),
                        'scan_count': len(power_arrays),
                    },
                )
                rolled += 1

        return rolled

    def _rollup_summaries(self, source_resolution, cutoff, bucket_seconds, dry_run,
                          align_to_bucket, elementwise_max, weighted_mean):
        """Roll up finer ScanSummary rows into coarser buckets."""
        summaries = list(
            ScanSummary.objects.filter(
                scanner=self,
                bucket_seconds=source_resolution,
                bucket_start__lt=cutoff,
            ).order_by('bucket_start')
        )

        if not summaries:
            return 0

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

        from core.retention import uniform_length_subset

        rolled = 0
        with transaction.atomic():
            for (band_id, bucket_start), items in buckets.items():
                items = [s for s in items if s.peak_power]
                if not items:
                    continue

                # Truncate near-equal summaries to a common grid; drop only
                # drastically-short ones. peak_power and avg_power of a summary
                # share a length, so weighted_mean() below stays consistent.
                peak_arrays, dropped, target = uniform_length_subset(
                    [s.peak_power for s in items]
                )
                if not peak_arrays:
                    continue
                if dropped:
                    logger.warning(
                        "rollup %s band %s %s: dropped %d short summary(ies); "
                        "kept %d at length %d",
                        self.id, band_id, bucket_start.isoformat(),
                        dropped, len(peak_arrays), target,
                    )

                peak = elementwise_max(peak_arrays)
                avg, total_count = weighted_mean(items)

                ref = next((s for s in items if len(s.peak_power) == target), items[0])
                ScanSummary.objects.update_or_create(
                    scanner=self,
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

        return rolled

    def _purge_scans(self, cutoff, dry_run, batch_size):
        """Delete raw Scan rows older than cutoff."""
        qs = Scan.objects.filter(scanner=self, timestamp__lt=cutoff)
        count = qs.count()

        if count == 0:
            return 0

        if dry_run:
            return count

        deleted_total = 0
        while True:
            batch_ids = list(qs.order_by('pk').values_list('pk', flat=True)[:batch_size])
            if not batch_ids:
                break
            with transaction.atomic():
                deleted, _ = Scan.objects.filter(pk__in=batch_ids).delete()
            deleted_total += deleted

        return deleted_total

    def _purge_summaries(self, resolution, cutoff, dry_run, batch_size):
        """Delete ScanSummary rows of a given resolution older than cutoff."""
        qs = ScanSummary.objects.filter(
            scanner=self,
            bucket_seconds=resolution,
            bucket_start__lt=cutoff,
        )
        count = qs.count()

        if count == 0:
            return 0

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


class UserMQTTCredentials(models.Model):
    """MQTT credentials for a Django user (read-only access to scan data)."""

    user = models.OneToOneField(
        'auth.User',
        on_delete=models.CASCADE,
        related_name='mqtt_credentials',
        primary_key=True
    )
    mqtt_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    auth_token = models.CharField(max_length=64, default=generate_auth_token)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'User MQTT Credentials'
        verbose_name_plural = 'User MQTT Credentials'

    def __str__(self):
        return f"MQTT credentials for {self.user.username}"

    def regenerate_token(self):
        self.auth_token = generate_auth_token()
        self.save(update_fields=['auth_token', 'updated_at'])


class Band(models.Model):
    """A frequency band configured for a specific scanner."""

    scanner = models.ForeignKey(Scanner, on_delete=models.CASCADE, related_name='bands')

    name = models.CharField(max_length=100)
    start_hz = models.BigIntegerField()
    stop_hz = models.BigIntegerField()
    enabled = models.BooleanField(default=True)
    description = models.TextField(blank=True)

    # Display settings
    color = models.CharField(max_length=20, default='#3b82f6')  # Tailwind blue-500

    # Scanner-specific settings for this band
    antenna = models.CharField(max_length=10, blank=True)  # A, B, etc.

    class Meta:
        ordering = ['start_hz']
        unique_together = ['scanner', 'name']

    def __str__(self):
        status = "enabled" if self.enabled else "disabled"
        return f"{self.scanner.name} - {self.name} ({self.start_hz/1e6:.1f}-{self.stop_hz/1e6:.1f} MHz) [{status}]"

    @property
    def start_mhz(self):
        return self.start_hz / 1_000_000

    @property
    def stop_mhz(self):
        return self.stop_hz / 1_000_000


class Scan(models.Model):
    """A stored spectrum scan."""

    scanner = models.ForeignKey(Scanner, on_delete=models.CASCADE, related_name='scans')
    band = models.ForeignKey(Band, on_delete=models.SET_NULL, null=True, blank=True)

    timestamp = models.DateTimeField(db_index=True)
    hz_lo = models.BigIntegerField()
    hz_hi = models.BigIntegerField()
    step_hz = models.FloatField()

    # Power data stored as JSON array
    power = models.JSONField()

    # Metadata
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['scanner', 'timestamp']),
            models.Index(fields=['band', 'timestamp']),
            models.Index(fields=['scanner', 'band', 'timestamp']),
        ]

    def __str__(self):
        return f"{self.scanner.name} @ {self.timestamp}"

    @property
    def bin_count(self):
        return len(self.power) if self.power else 0


class ShareLink(models.Model):
    """Shareable read-only access links for demo/viewing purposes."""

    token = models.CharField(max_length=64, unique=True, default=generate_auth_token)
    label = models.CharField(max_length=100, help_text="Descriptive label (e.g., 'Super Bowl Demo')")

    # Access control
    is_active = models.BooleanField(default=True, help_text="Inactive links are revoked")
    expires_at = models.DateTimeField(null=True, blank=True, help_text="Optional expiration time")

    # Tracking
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        'auth.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='share_links'
    )
    last_used_at = models.DateTimeField(null=True, blank=True)
    use_count = models.IntegerField(default=0)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        status = "active" if self.is_active else "revoked"
        return f"{self.label} ({status})"

    def is_valid(self):
        """Check if link is active and not expired."""
        if not self.is_active:
            return False
        if self.expires_at:
            from django.utils import timezone
            if timezone.now() > self.expires_at:
                return False
        return True

    def record_use(self):
        """Record that this link was used."""
        from django.utils import timezone
        self.last_used_at = timezone.now()
        self.use_count += 1
        self.save(update_fields=['last_used_at', 'use_count'])


class ScannerGroup(models.Model):
    """A logical group of scanners (event, venue, tour, etc.)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)

    created_by = models.ForeignKey(
        'auth.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='scanner_groups'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Scanner Group'
        verbose_name_plural = 'Scanner Groups'
        ordering = ['-created_at']

    def __str__(self):
        return self.name


class MonitoredFrequency(models.Model):
    """A specific RF frequency to monitor (wireless mic channel, IEM, etc.)."""

    CATEGORY_CHOICES = [
        ('Wireless Mics', 'Wireless Mics'),
        ('IEMs', 'IEMs'),
        ('Comms', 'Comms'),
        ('Intercom', 'Intercom'),
        ('WiFi', 'WiFi'),
        ('Other', 'Other'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    frequency_hz = models.BigIntegerField(help_text='Exact frequency in Hz')
    name = models.CharField(max_length=100, help_text='e.g. "Vox 1", "IEM Mix L"')

    # Scope: assigned to specific scanners and/or groups. Both empty = global.
    scanners = models.ManyToManyField(Scanner, blank=True, related_name='monitored_frequencies')
    groups = models.ManyToManyField(ScannerGroup, blank=True, related_name='monitored_frequencies')

    color = models.CharField(max_length=20, blank=True, help_text='Hex color (auto-assigned if empty)')
    category = models.CharField(max_length=50, choices=CATEGORY_CHOICES, default='Wireless Mics')
    notes = models.TextField(blank=True)
    active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Monitored Frequency'
        verbose_name_plural = 'Monitored Frequencies'
        ordering = ['frequency_hz']

    def __str__(self):
        return f"{self.name} ({self.frequency_hz / 1e6:.3f} MHz)"

    @property
    def frequency_mhz(self):
        return self.frequency_hz / 1_000_000

    def save(self, *args, **kwargs):
        if not self.color:
            palette = ['#ff8c00', '#ff00ff', '#00ff00', '#ff4444', '#00bfff', '#ffff00', '#ff69b4', '#7fff00']
            count = MonitoredFrequency.objects.count()
            self.color = palette[count % len(palette)]
        super().save(*args, **kwargs)


def get_monitored_frequencies_for_scanner(scanner):
    """Resolve monitored frequencies for a scanner.

    Returns frequencies where:
    - Scanner is directly in the scanners M2M, OR
    - Any of the scanner's groups is in the groups M2M, OR
    - Both M2M fields are empty (global frequency)
    """
    scanner_group_ids = scanner.scanner_groups.values_list('id', flat=True)

    return MonitoredFrequency.objects.filter(active=True).annotate(
        scanner_count=Count('scanners'),
        group_count=Count('groups'),
    ).filter(
        Q(scanners=scanner) |                          # direct assignment
        Q(groups__id__in=scanner_group_ids) |           # via group
        Q(scanner_count=0, group_count=0)               # global (both empty)
    ).distinct()


class Access(models.Model):
    """Permission grant scoped to a scanner group or scanner, for a user or token."""

    PERMISSION_CHOICES = [
        ('r', 'Read'),
        ('rw', 'Read/Write'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Who — exactly one of these is set (a user, a Django group, or a token)
    user = models.ForeignKey(
        'auth.User',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='access_grants'
    )
    group = models.ForeignKey(
        'auth.Group',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='access_grants',
        help_text="Grant to every member of this Django group (e.g. SSO users)",
    )
    token = models.CharField(
        max_length=64,
        null=True,
        blank=True,
        unique=True,
        default=None,
    )

    # What — exactly one of these is set
    scanner_group = models.ForeignKey(
        ScannerGroup,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='access_grants'
    )
    scanner = models.ForeignKey(
        Scanner,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='access_grants'
    )

    permission = models.CharField(max_length=2, choices=PERMISSION_CHOICES, default='r')
    label = models.CharField(max_length=100, blank=True, help_text="Descriptive label")
    is_active = models.BooleanField(default=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    # Tracking
    created_by = models.ForeignKey(
        'auth.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='access_grants_created'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    use_count = models.IntegerField(default=0)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(user__isnull=False, token__isnull=True, group__isnull=True) |
                    models.Q(user__isnull=True, token__isnull=False, group__isnull=True) |
                    models.Q(user__isnull=True, token__isnull=True, group__isnull=False)
                ),
                name='access_exactly_one_principal',
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(scanner_group__isnull=False, scanner__isnull=True) |
                    models.Q(scanner_group__isnull=True, scanner__isnull=False)
                ),
                name='access_exactly_one_scope',
            ),
        ]

    def __str__(self):
        if self.user:
            who = self.user.username
        elif self.group_id:
            who = f"group:{self.group.name}"
        else:
            who = f"token:{self.token[:12]}..."
        what = self.scanner_group.name if self.scanner_group else str(self.scanner)
        return f"{who} -> {what} ({self.get_permission_display()})"

    def is_valid(self):
        """Check if access grant is active and not expired."""
        if not self.is_active:
            return False
        if self.expires_at:
            from django.utils import timezone
            if timezone.now() > self.expires_at:
                return False
        return True

    def record_use(self):
        """Record that this access was used."""
        from django.utils import timezone
        self.last_used_at = timezone.now()
        self.use_count += 1
        self.save(update_fields=['last_used_at', 'use_count'])


class SiteSettings(models.Model):
    """Global key-value settings store."""

    name = models.CharField(max_length=100, unique=True)
    value = models.JSONField()
    description = models.CharField(max_length=200, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Site Setting'
        verbose_name_plural = 'Site Settings'
        ordering = ['name']

    def __str__(self):
        return self.name

    @classmethod
    def get(cls, name, default=None):
        """Get a setting value by name."""
        try:
            return cls.objects.get(name=name).value
        except cls.DoesNotExist:
            return default


class ScanSummary(models.Model):
    """Pre-computed scan summary for a time bucket (TSDB-style rollup)."""

    scanner = models.ForeignKey(Scanner, on_delete=models.CASCADE, related_name='scan_summaries')
    band = models.ForeignKey('Band', on_delete=models.SET_NULL, null=True, blank=True)

    bucket_start = models.DateTimeField(db_index=True)
    bucket_seconds = models.IntegerField()

    hz_lo = models.BigIntegerField()
    hz_hi = models.BigIntegerField()
    step_hz = models.FloatField()

    peak_power = models.JSONField()
    avg_power = models.JSONField()
    scan_count = models.IntegerField()

    class Meta:
        verbose_name = 'Scan Summary'
        verbose_name_plural = 'Scan Summaries'
        ordering = ['-bucket_start']
        constraints = [
            models.UniqueConstraint(
                fields=['scanner', 'band', 'bucket_start', 'bucket_seconds'],
                name='unique_scan_summary_bucket',
            ),
        ]
        indexes = [
            models.Index(fields=['scanner', 'bucket_start']),
            models.Index(fields=['scanner', 'band', 'bucket_start']),
        ]

    def __str__(self):
        return f"{self.scanner.name} {self.bucket_seconds}s @ {self.bucket_start}"
