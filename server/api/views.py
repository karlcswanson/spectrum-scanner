"""API views for Spectrum Server."""

from datetime import timedelta
from django.utils import timezone
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response

from core.models import Scanner, Band, Scan
from .serializers import (
    ScannerSerializer, BandSerializer, ScanSerializer, ScanCreateSerializer,
    ScanTimelineSerializer
)


class ScannerViewSet(viewsets.ModelViewSet):
    """API endpoint for scanners."""

    queryset = Scanner.objects.all()
    serializer_class = ScannerSerializer

    @action(detail=True, methods=['post'])
    def start(self, request, pk=None):
        """Send start command to scanner via MQTT."""
        scanner = self.get_object()
        # TODO: Publish to MQTT spectrum/commands/{id}/start
        return Response({'status': 'start command sent', 'scanner': scanner.id})

    @action(detail=True, methods=['post'])
    def stop(self, request, pk=None):
        """Send stop command to scanner via MQTT."""
        scanner = self.get_object()
        # TODO: Publish to MQTT spectrum/commands/{id}/stop
        return Response({'status': 'stop command sent', 'scanner': scanner.id})

    @action(detail=True, methods=['get'])
    def latest_scan(self, request, pk=None):
        """Get the most recent scan from this scanner."""
        scanner = self.get_object()
        scan = scanner.scans.first()
        if scan:
            return Response(ScanSerializer(scan).data)
        return Response({'detail': 'No scans found'}, status=status.HTTP_404_NOT_FOUND)

    @action(detail=True, methods=['get'])
    def history(self, request, pk=None):
        """Get historical scans for this scanner.

        Query params:
        - band: Filter by band name
        - hours: How far back to look (default 24, max 24)
        - limit: Max scans to return (default 1000)
        """
        scanner = self.get_object()
        band_name = request.query_params.get('band')
        hours = min(int(request.query_params.get('hours', 24)), 24)
        limit = min(int(request.query_params.get('limit', 1000)), 1000)

        cutoff = timezone.now() - timedelta(hours=hours)
        queryset = scanner.scans.filter(timestamp__gte=cutoff).order_by('timestamp')

        if band_name:
            queryset = queryset.filter(band__name=band_name)

        scans = queryset[:limit]
        return Response(ScanSerializer(scans, many=True).data)

    @action(detail=True, methods=['get'])
    def timeline(self, request, pk=None):
        """Get scan timestamps for timeline/scrubber display.

        Returns timestamps only (no power data) for efficient timeline rendering.

        Query params:
        - band: Filter by band name
        - hours: How far back to look (default 24, max 24)
        """
        scanner = self.get_object()
        band_name = request.query_params.get('band')
        hours = min(int(request.query_params.get('hours', 24)), 24)

        cutoff = timezone.now() - timedelta(hours=hours)
        queryset = scanner.scans.filter(timestamp__gte=cutoff).order_by('timestamp')

        if band_name:
            queryset = queryset.filter(band__name=band_name)

        # Return only timestamps and IDs for the timeline
        scans = queryset.values('id', 'timestamp', 'band__name')
        return Response(list(scans))


class BandViewSet(viewsets.ModelViewSet):
    """API endpoint for frequency bands."""

    queryset = Band.objects.all()
    serializer_class = BandSerializer


class ScanViewSet(viewsets.ModelViewSet):
    """API endpoint for scans."""

    queryset = Scan.objects.select_related('scanner', 'band').all()
    serializer_class = ScanSerializer

    def get_queryset(self):
        queryset = super().get_queryset()

        # Filter by scanner
        scanner_id = self.request.query_params.get('scanner')
        if scanner_id:
            queryset = queryset.filter(scanner_id=scanner_id)

        # Filter by band name
        band_name = self.request.query_params.get('band')
        if band_name:
            queryset = queryset.filter(band__name=band_name)

        # Filter by band ID
        band_id = self.request.query_params.get('band_id')
        if band_id:
            queryset = queryset.filter(band_id=band_id)

        # Time-based filtering
        hours = self.request.query_params.get('hours')
        if hours:
            cutoff = timezone.now() - timedelta(hours=int(hours))
            queryset = queryset.filter(timestamp__gte=cutoff)

        start_time = self.request.query_params.get('start')
        if start_time:
            from dateutil.parser import parse as parse_datetime
            queryset = queryset.filter(timestamp__gte=parse_datetime(start_time))

        end_time = self.request.query_params.get('end')
        if end_time:
            from dateutil.parser import parse as parse_datetime
            queryset = queryset.filter(timestamp__lte=parse_datetime(end_time))

        # Limit results (default 100)
        limit = int(self.request.query_params.get('limit', 100))
        return queryset[:limit]

    def create(self, request, *args, **kwargs):
        """Create a new scan from incoming data."""
        serializer = ScanCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        scan = serializer.save()
        return Response(ScanSerializer(scan).data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=['get'])
    def at_time(self, request):
        """Get scans closest to a specific timestamp.

        Query params:
        - time: ISO timestamp to find scans near
        - scanner: Scanner ID (required)
        - band: Band name (optional)
        """
        scanner_id = request.query_params.get('scanner')
        timestamp_str = request.query_params.get('time')
        band_name = request.query_params.get('band')

        if not scanner_id or not timestamp_str:
            return Response(
                {'error': 'scanner and time query params required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        from datetime import datetime, timezone as dt_timezone

        # Parse ISO timestamp - handle 'Z' suffix for UTC
        timestamp_str = timestamp_str.replace('Z', '+00:00')
        try:
            target_time = datetime.fromisoformat(timestamp_str)
        except ValueError:
            # Fallback for other formats
            from dateutil.parser import parse as parse_datetime
            target_time = parse_datetime(timestamp_str)

        # Ensure timezone-aware for comparison with Django timestamps
        if target_time.tzinfo is None:
            target_time = target_time.replace(tzinfo=dt_timezone.utc)

        # Find the closest scan to the target time
        queryset = Scan.objects.filter(scanner_id=scanner_id)
        if band_name:
            queryset = queryset.filter(band__name=band_name)

        # Get one scan before and one after target time
        before = queryset.filter(timestamp__lte=target_time).order_by('-timestamp').first()
        after = queryset.filter(timestamp__gte=target_time).order_by('timestamp').first()

        # Return the closest one
        if before and after:
            if (target_time - before.timestamp) <= (after.timestamp - target_time):
                scan = before
            else:
                scan = after
        else:
            scan = before or after

        if scan:
            return Response(ScanSerializer(scan).data)
        return Response({'detail': 'No scans found'}, status=status.HTTP_404_NOT_FOUND)
