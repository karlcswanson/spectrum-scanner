"""Core models for Spectrum Server."""

import secrets
import uuid

from django.db import models


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

    # Authentication
    auth_token = models.CharField(max_length=64, default=generate_auth_token)
    enabled = models.BooleanField(default=True, help_text="Disabled scanners cannot connect")

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

    def regenerate_token(self):
        """Generate a new auth token for this scanner."""
        self.auth_token = generate_auth_token()
        self.save(update_fields=['auth_token'])


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
