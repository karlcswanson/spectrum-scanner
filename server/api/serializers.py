"""API serializers for Spectrum Server."""

from rest_framework import serializers
from core.models import Scanner, Band, Scan, ScanSummary, ScannerGroup, MonitoredFrequency, Access


class BandSerializer(serializers.ModelSerializer):
    start_mhz = serializers.FloatField(read_only=True)
    stop_mhz = serializers.FloatField(read_only=True)

    class Meta:
        model = Band
        fields = ['id', 'name', 'start_hz', 'stop_hz', 'start_mhz', 'stop_mhz', 'enabled', 'description', 'color']


class ScannerSerializer(serializers.ModelSerializer):
    bands = BandSerializer(many=True, read_only=True)
    scanner_groups = serializers.PrimaryKeyRelatedField(many=True, read_only=True)
    user_permission = serializers.SerializerMethodField()

    class Meta:
        model = Scanner
        fields = [
            'id', 'name', 'scanner_type', 'location', 'description',
            'online', 'scanning', 'current_band', 'last_seen',
            'bands', 'scanner_groups', 'user_permission', 'created_at', 'updated_at'
        ]
        read_only_fields = ['online', 'scanning', 'current_band', 'last_seen', 'bands', 'scanner_groups', 'created_at', 'updated_at']

    def get_user_permission(self, obj):
        """Return the current user's permission level for this scanner."""
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return None
        if request.user.is_staff:
            return 'rw'
        from api.permissions import get_active_grants
        grants = get_active_grants(request.user)
        # Check direct scanner grants
        scanner_grants = grants.filter(scanner=obj)
        # Check group grants
        group_ids = obj.scanner_groups.values_list('id', flat=True)
        group_grants = grants.filter(scanner_group_id__in=group_ids)
        all_grants = scanner_grants | group_grants
        if all_grants.filter(permission='rw').exists():
            return 'rw'
        if all_grants.exists():
            return 'r'
        return None


class ScanSerializer(serializers.ModelSerializer):
    scanner_id = serializers.UUIDField(source='scanner.id', read_only=True)
    scanner_name = serializers.CharField(source='scanner.name', read_only=True)
    band_name = serializers.CharField(source='band.name', read_only=True, allow_null=True)

    class Meta:
        model = Scan
        fields = [
            'id', 'scanner_id', 'scanner_name', 'band_name',
            'timestamp', 'hz_lo', 'hz_hi', 'step_hz', 'power', 'metadata', 'bin_count'
        ]


class ScanSummaryAsScanSerializer(serializers.ModelSerializer):
    """Serialize ScanSummary in the same shape as ScanSerializer.

    The frontend doesn't need to know whether it's viewing raw scans
    or rolled-up summaries — the data format is identical.
    """

    id = serializers.IntegerField(source='pk', read_only=True)
    scanner_id = serializers.UUIDField(source='scanner.id', read_only=True)
    scanner_name = serializers.CharField(source='scanner.name', read_only=True)
    band_name = serializers.CharField(source='band.name', read_only=True, allow_null=True)
    timestamp = serializers.DateTimeField(source='bucket_start', read_only=True)
    power = serializers.JSONField(source='peak_power', read_only=True)
    metadata = serializers.SerializerMethodField()
    bin_count = serializers.SerializerMethodField()

    class Meta:
        model = ScanSummary
        fields = [
            'id', 'scanner_id', 'scanner_name', 'band_name',
            'timestamp', 'hz_lo', 'hz_hi', 'step_hz', 'power', 'metadata', 'bin_count'
        ]

    def get_metadata(self, obj):
        return {'source': 'summary', 'scan_count': obj.scan_count, 'bucket_seconds': obj.bucket_seconds}

    def get_bin_count(self, obj):
        return len(obj.peak_power) if obj.peak_power else 0


class DecimatedScanSummarySerializer(serializers.ModelSerializer):
    """Decimated version of ScanSummary for scrubber preview."""

    id = serializers.IntegerField(source='pk', read_only=True)
    scanner_id = serializers.UUIDField(source='scanner.id', read_only=True)
    band_name = serializers.CharField(source='band.name', read_only=True, allow_null=True)
    timestamp = serializers.DateTimeField(source='bucket_start', read_only=True)
    power = serializers.SerializerMethodField()

    class Meta:
        model = ScanSummary
        fields = [
            'id', 'scanner_id', 'band_name',
            'timestamp', 'hz_lo', 'hz_hi', 'step_hz', 'power'
        ]

    def get_power(self, obj):
        if not obj.peak_power:
            return []
        target_points = 1920
        original = obj.peak_power
        if len(original) <= target_points:
            return original
        factor = len(original) / target_points
        result = []
        for i in range(target_points):
            start = int(i * factor)
            end = int((i + 1) * factor)
            chunk = original[start:end]
            if chunk:
                result.append(max(chunk))
        return result


class ScannerGroupSerializer(serializers.ModelSerializer):
    scanner_count = serializers.SerializerMethodField()
    scanners_online = serializers.SerializerMethodField()

    class Meta:
        model = ScannerGroup
        fields = [
            'id', 'name', 'description', 'start_date', 'end_date',
            'scanner_count', 'scanners_online', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def get_scanner_count(self, obj):
        return obj.scanners.count()

    def get_scanners_online(self, obj):
        return obj.scanners.filter(online=True).count()


class ScannerGroupDetailSerializer(ScannerGroupSerializer):
    scanners = ScannerSerializer(many=True, read_only=True)

    class Meta(ScannerGroupSerializer.Meta):
        fields = ScannerGroupSerializer.Meta.fields + ['scanners']


class MonitoredFrequencySerializer(serializers.ModelSerializer):
    frequency_mhz = serializers.FloatField(read_only=True)

    class Meta:
        model = MonitoredFrequency
        fields = ['id', 'frequency_hz', 'frequency_mhz', 'name', 'color', 'category', 'notes', 'active']


class AccessSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source='user.username', read_only=True, default=None)
    scanner_group_name = serializers.CharField(source='scanner_group.name', read_only=True, default=None)
    scanner_name = serializers.CharField(source='scanner.name', read_only=True, default=None)

    class Meta:
        model = Access
        fields = [
            'id', 'user', 'token', 'scanner_group', 'scanner',
            'permission', 'label', 'is_active', 'expires_at',
            'username', 'scanner_group_name', 'scanner_name',
            'created_at', 'updated_at', 'last_used_at', 'use_count'
        ]
        read_only_fields = ['id', 'token', 'created_at', 'updated_at', 'last_used_at', 'use_count']


class DecimatedScanSerializer(serializers.ModelSerializer):
    """Serializer that decimates power array to ~1920 points for fast scrubbing."""

    scanner_id = serializers.UUIDField(source='scanner.id', read_only=True)
    band_name = serializers.CharField(source='band.name', read_only=True, allow_null=True)
    power = serializers.SerializerMethodField()

    class Meta:
        model = Scan
        fields = [
            'id', 'scanner_id', 'band_name',
            'timestamp', 'hz_lo', 'hz_hi', 'step_hz', 'power'
        ]

    def get_power(self, obj):
        """Decimate power array to ~1920 points using max-pooling."""
        if not obj.power:
            return []

        target_points = 1920
        original = obj.power

        if len(original) <= target_points:
            return original

        # Calculate decimation factor
        factor = len(original) / target_points
        result = []

        for i in range(target_points):
            start = int(i * factor)
            end = int((i + 1) * factor)
            # Use max value in each bin to preserve peaks
            chunk = original[start:end]
            if chunk:
                result.append(max(chunk))

        return result


class ScanCreateSerializer(serializers.Serializer):
    """Serializer for incoming scan data (from MQTT or direct POST)."""

    source = serializers.DictField()
    scan = serializers.DictField()
    metadata = serializers.DictField(required=False, default=dict)

    def create(self, validated_data):
        from django.utils import timezone
        from dateutil.parser import parse as parse_datetime

        source = validated_data['source']
        scan_data = validated_data['scan']
        metadata = validated_data.get('metadata', {})

        # Get or create scanner
        scanner, _ = Scanner.objects.get_or_create(
            id=source['id'],
            defaults={
                'name': source.get('name', source['id']),
                'scanner_type': source.get('type', 'pluto'),
                'location': source.get('location', ''),
            }
        )

        # Update scanner status
        scanner.online = True
        scanner.last_seen = timezone.now()
        if scan_data.get('band'):
            scanner.current_band = scan_data['band']
        scanner.save()

        # Find matching band
        band = None
        if scan_data.get('band'):
            band = Band.objects.filter(name=scan_data['band']).first()

        # Parse timestamp
        timestamp = scan_data.get('timestamp')
        if isinstance(timestamp, str):
            timestamp = parse_datetime(timestamp)
        elif timestamp is None:
            timestamp = timezone.now()

        # Create scan
        scan = Scan.objects.create(
            scanner=scanner,
            band=band,
            timestamp=timestamp,
            hz_lo=int(scan_data['hz_lo']),
            hz_hi=int(scan_data['hz_hi']),
            step_hz=float(scan_data['step']),
            power=scan_data['power'],
            metadata=metadata,
        )

        return scan
