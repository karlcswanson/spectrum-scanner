"""API views for Spectrum Server."""

from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response

from core.models import Scanner, Band, Scan
from .serializers import ScannerSerializer, BandSerializer, ScanSerializer, ScanCreateSerializer


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

        # Filter by band
        band_id = self.request.query_params.get('band')
        if band_id:
            queryset = queryset.filter(band_id=band_id)

        # Limit results (default 100)
        limit = int(self.request.query_params.get('limit', 100))
        return queryset[:limit]

    def create(self, request, *args, **kwargs):
        """Create a new scan from incoming data."""
        serializer = ScanCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        scan = serializer.save()
        return Response(ScanSerializer(scan).data, status=status.HTTP_201_CREATED)
