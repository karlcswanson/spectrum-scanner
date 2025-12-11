"""API serializers for Spectrum Server."""

from rest_framework import serializers
from core.models import Scanner, Band, Scan


class BandSerializer(serializers.ModelSerializer):
    start_mhz = serializers.FloatField(read_only=True)
    stop_mhz = serializers.FloatField(read_only=True)

    class Meta:
        model = Band
        fields = ['id', 'name', 'start_hz', 'stop_hz', 'start_mhz', 'stop_mhz', 'enabled', 'description', 'color']


class ScannerSerializer(serializers.ModelSerializer):
    bands = BandSerializer(many=True, read_only=True)

    class Meta:
        model = Scanner
        fields = [
            'id', 'name', 'scanner_type', 'location', 'description',
            'online', 'scanning', 'current_band', 'last_seen', 'config',
            'bands', 'created_at', 'updated_at'
        ]
        read_only_fields = ['online', 'scanning', 'current_band', 'last_seen', 'bands', 'created_at', 'updated_at']


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


class ScanTimelineSerializer(serializers.ModelSerializer):
    """Lightweight serializer for timeline display (no power data)."""

    band_name = serializers.CharField(source='band.name', read_only=True, allow_null=True)

    class Meta:
        model = Scan
        fields = ['id', 'timestamp', 'band_name']


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
