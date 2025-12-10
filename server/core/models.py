"""Core models for Spectrum Server."""

from django.db import models


class Scanner(models.Model):
    """A spectrum scanner device (Pluto, SCPI analyzer, etc.)."""

    SCANNER_TYPES = [
        ('pluto', 'ADALM-Pluto'),
        ('scpi-tti', 'TTi PSA Series'),
        ('scpi-owon', 'OWON XSA/HSA Series'),
        ('scpi-generic', 'Generic SCPI'),
        ('import', 'Imported Scan'),
    ]

    id = models.CharField(max_length=100, primary_key=True)
    name = models.CharField(max_length=200)
    scanner_type = models.CharField(max_length=20, choices=SCANNER_TYPES)
    location = models.CharField(max_length=200, blank=True)
    description = models.TextField(blank=True)

    # Status (updated via MQTT)
    online = models.BooleanField(default=False)
    scanning = models.BooleanField(default=False)
    current_band = models.CharField(max_length=100, blank=True)
    last_seen = models.DateTimeField(null=True, blank=True)

    # Configuration
    config = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.scanner_type})"


class BandTemplate(models.Model):
    """Predefined band templates (for easy setup of new scanners)."""

    name = models.CharField(max_length=100, unique=True)
    start_hz = models.BigIntegerField()
    stop_hz = models.BigIntegerField()
    description = models.TextField(blank=True)
    color = models.CharField(max_length=20, default='#3b82f6')

    class Meta:
        ordering = ['start_hz']

    def __str__(self):
        return f"{self.name} ({self.start_hz/1e6:.1f}-{self.stop_hz/1e6:.1f} MHz)"


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
    dwell_time_ms = models.IntegerField(null=True, blank=True)  # Override scanner default

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
        ]

    def __str__(self):
        return f"{self.scanner.name} @ {self.timestamp}"

    @property
    def bin_count(self):
        return len(self.power) if self.power else 0


class ScanAggregate(models.Model):
    """Aggregated scan data (max hold, average over time period)."""

    AGGREGATE_TYPES = [
        ('max', 'Max Hold'),
        ('min', 'Min Hold'),
        ('avg', 'Average'),
    ]

    PERIOD_TYPES = [
        ('hour', 'Hourly'),
        ('day', 'Daily'),
        ('week', 'Weekly'),
    ]

    scanner = models.ForeignKey(Scanner, on_delete=models.CASCADE, related_name='aggregates')
    band = models.ForeignKey(Band, on_delete=models.SET_NULL, null=True, blank=True)

    aggregate_type = models.CharField(max_length=10, choices=AGGREGATE_TYPES)
    period_type = models.CharField(max_length=10, choices=PERIOD_TYPES)
    period_start = models.DateTimeField()
    period_end = models.DateTimeField()

    hz_lo = models.BigIntegerField()
    hz_hi = models.BigIntegerField()
    step_hz = models.FloatField()
    power = models.JSONField()

    scan_count = models.IntegerField(default=0)

    class Meta:
        ordering = ['-period_start']
        unique_together = ['scanner', 'band', 'aggregate_type', 'period_type', 'period_start']

    def __str__(self):
        return f"{self.scanner.name} {self.aggregate_type} ({self.period_type}) @ {self.period_start}"
