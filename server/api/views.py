"""API views for Spectrum Server."""

import logging
from datetime import timedelta
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.http import HttpResponse
from rest_framework import viewsets, status
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated, BasePermission, SAFE_METHODS
from rest_framework.response import Response

from django.contrib.auth import authenticate, login, logout

from core.models import Scanner, Band, Scan, UserMQTTCredentials, ScannerGroup, Access
from .serializers import (
    ScannerSerializer, BandSerializer, ScanSerializer, ScanCreateSerializer,
    DecimatedScanSerializer, ScannerGroupSerializer, ScannerGroupDetailSerializer,
    AccessSerializer
)

logger = logging.getLogger(__name__)


class ReadOnlyIfShareSession(BasePermission):
    """Allow read-only access for share link sessions, full access for others."""

    def has_permission(self, request, view):
        # Always allow safe methods (GET, HEAD, OPTIONS)
        if request.method in SAFE_METHODS:
            return True

        # Block write operations for readonly sessions
        if request.session.get('readonly'):
            return False

        # Allow write operations for normal authenticated users
        return True


class ScannerViewSet(viewsets.ModelViewSet):
    """API endpoint for scanners."""

    queryset = Scanner.objects.all()
    serializer_class = ScannerSerializer
    permission_classes = [IsAuthenticated, ReadOnlyIfShareSession]

    def get_queryset(self):
        queryset = super().get_queryset()
        group_id = self.request.query_params.get('group')
        if group_id:
            queryset = queryset.filter(scanner_groups__id=group_id)
        if self.request.query_params.get('pool', '').lower() == 'true':
            queryset = queryset.filter(scanner_groups__isnull=True)
        return queryset

    @action(detail=True, methods=['post'])
    def start(self, request, pk=None):
        """Send start command to scanner via MQTT."""
        from realtime.mqtt_commands import start_scanner
        scanner = self.get_object()
        success = start_scanner(str(scanner.id))
        if success:
            return Response({'status': 'start command sent', 'scanner': scanner.id})
        return Response(
            {'error': 'Failed to send start command'},
            status=status.HTTP_503_SERVICE_UNAVAILABLE
        )

    @action(detail=True, methods=['post'])
    def stop(self, request, pk=None):
        """Send stop command to scanner via MQTT."""
        from realtime.mqtt_commands import stop_scanner
        scanner = self.get_object()
        success = stop_scanner(str(scanner.id))
        if success:
            return Response({'status': 'stop command sent', 'scanner': scanner.id})
        return Response(
            {'error': 'Failed to send stop command'},
            status=status.HTTP_503_SERVICE_UNAVAILABLE
        )

    @action(detail=True, methods=['post'])
    def push_bands(self, request, pk=None):
        """Push band configuration to scanner via MQTT.

        POST data: [{"name": "UHF", "enabled": true, "start_hz": 470000000, "stop_hz": 608000000}, ...]
        """
        from realtime.mqtt_commands import update_bands
        scanner = self.get_object()
        bands = request.data
        if not isinstance(bands, list):
            return Response(
                {'error': 'Expected list of band configs'},
                status=status.HTTP_400_BAD_REQUEST
            )
        success = update_bands(str(scanner.id), bands)
        if success:
            return Response({'status': 'bands pushed', 'scanner': scanner.id})
        return Response(
            {'error': 'Failed to push bands'},
            status=status.HTTP_503_SERVICE_UNAVAILABLE
        )

    @action(detail=True, methods=['post'])
    def push_gain(self, request, pk=None):
        """Push gain settings to scanner via MQTT.

        POST data: {"rx_gain": 40, "rx_gain_mode": "manual"}
        """
        from realtime.mqtt_commands import update_gain
        scanner = self.get_object()
        rx_gain = request.data.get('rx_gain')
        rx_gain_mode = request.data.get('rx_gain_mode')
        if rx_gain is None:
            return Response(
                {'error': 'rx_gain required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        success = update_gain(str(scanner.id), float(rx_gain), rx_gain_mode)
        if success:
            return Response({'status': 'gain pushed', 'scanner': scanner.id})
        return Response(
            {'error': 'Failed to push gain'},
            status=status.HTTP_503_SERVICE_UNAVAILABLE
        )

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
        - hours: How far back to look (default 24) - relative to now
        - start: ISO timestamp for range start (overrides hours)
        - end: ISO timestamp for range end (defaults to now)
        - limit: Max scans to return (default 1000)
        - decimated: If true, downsample power arrays to ~1920 points
        """
        from dateutil.parser import parse as parse_datetime

        scanner = self.get_object()
        band_name = request.query_params.get('band')
        limit = min(int(request.query_params.get('limit', 1000)), 5000)
        decimated = request.query_params.get('decimated', '').lower() == 'true'

        # Determine time range
        start_param = request.query_params.get('start')
        end_param = request.query_params.get('end')

        if start_param:
            # Absolute time range
            try:
                start_time = parse_datetime(start_param)
                end_time = parse_datetime(end_param) if end_param else timezone.now()
            except Exception as e:
                logger.error(f"history: Failed to parse date params: start={start_param}, end={end_param}, error={e}")
                return Response({'error': f'Invalid date format: {e}'}, status=status.HTTP_400_BAD_REQUEST)
        else:
            # Relative hours (backwards compatible)
            try:
                hours_param = request.query_params.get('hours', '24')
                hours = float(hours_param) if hours_param and hours_param not in ('undefined', 'null', '') else 24
            except (ValueError, TypeError) as e:
                logger.error(f"history: Failed to parse hours param: {hours_param}, error={e}")
                hours = 24
            end_time = timezone.now()
            start_time = end_time - timedelta(hours=hours)

        queryset = scanner.scans.filter(
            timestamp__gte=start_time,
            timestamp__lte=end_time
        ).order_by('timestamp')

        if band_name:
            queryset = queryset.filter(band__name=band_name)

        scans = queryset[:limit]

        if decimated:
            # Return decimated scans for scrubber preview
            return Response(DecimatedScanSerializer(scans, many=True).data)

        return Response(ScanSerializer(scans, many=True).data)

    @action(detail=True, methods=['get'])
    def timeline(self, request, pk=None):
        """Get scan timestamps for timeline/scrubber display.

        Returns timestamps only (no power data) for efficient timeline rendering.

        Query params:
        - band: Filter by band name
        - hours: How far back to look (default 24) - relative to now
        - start: ISO timestamp for range start (overrides hours)
        - end: ISO timestamp for range end (defaults to now)
        """
        from dateutil.parser import parse as parse_datetime

        scanner = self.get_object()
        band_name = request.query_params.get('band')

        # Determine time range
        start_param = request.query_params.get('start')
        end_param = request.query_params.get('end')

        if start_param:
            # Absolute time range
            try:
                start_time = parse_datetime(start_param)
                end_time = parse_datetime(end_param) if end_param else timezone.now()
            except Exception as e:
                logger.error(f"timeline: Failed to parse date params: start={start_param}, end={end_param}, error={e}")
                return Response({'error': f'Invalid date format: {e}'}, status=status.HTTP_400_BAD_REQUEST)
        else:
            # Relative hours (backwards compatible)
            try:
                hours_param = request.query_params.get('hours', '24')
                hours = float(hours_param) if hours_param and hours_param not in ('undefined', 'null', '') else 24
            except (ValueError, TypeError) as e:
                logger.error(f"timeline: Failed to parse hours param: {hours_param}, error={e}")
                hours = 24
            end_time = timezone.now()
            start_time = end_time - timedelta(hours=hours)

        queryset = scanner.scans.filter(
            timestamp__gte=start_time,
            timestamp__lte=end_time
        ).order_by('timestamp')

        if band_name:
            queryset = queryset.filter(band__name=band_name)

        # Return only timestamps and IDs for the timeline
        scans = queryset.values('id', 'timestamp', 'band__name')
        return Response(list(scans))


class BandViewSet(viewsets.ModelViewSet):
    """API endpoint for frequency bands."""

    queryset = Band.objects.all()
    serializer_class = BandSerializer
    permission_classes = [IsAuthenticated, ReadOnlyIfShareSession]


class ScanViewSet(viewsets.ModelViewSet):
    """API endpoint for scans."""

    queryset = Scan.objects.select_related('scanner', 'band').all()
    serializer_class = ScanSerializer
    permission_classes = [IsAuthenticated, ReadOnlyIfShareSession]

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


@csrf_exempt
@api_view(['POST'])
@permission_classes([AllowAny])
def mqtt_auth(request):
    """Authenticate MQTT client connections.

    Called by mosquitto-go-auth plugin to validate credentials.
    Supports both scanners (publish) and frontend clients (subscribe-only).

    Expected POST data (form-encoded):
    - username: UUID (scanner or frontend client)
    - password: Auth token

    Returns:
    - 200 OK: Authentication successful
    - 403 Forbidden: Authentication failed
    """
    username = request.data.get('username', '')
    password = request.data.get('password', '')

    if not username or not password:
        logger.debug("MQTT auth: missing credentials, rejected")
        return HttpResponse(status=403)

    # Try bridge service account first (internal service for storing scans)
    from django.conf import settings
    bridge_username = getattr(settings, 'MQTT_BRIDGE_USERNAME', '')
    bridge_password = getattr(settings, 'MQTT_BRIDGE_PASSWORD', '')
    if bridge_username and username == bridge_username and password == bridge_password:
        logger.info(f"MQTT auth: bridge service authenticated")
        return HttpResponse(status=200)

    # Try scanner
    try:
        scanner = Scanner.objects.get(id=username)
        if scanner.enabled and scanner.auth_token == password:
            logger.info(f"MQTT auth: scanner {scanner.name} ({username[:8]}...) authenticated")
            return HttpResponse(status=200)
        else:
            reason = "disabled" if not scanner.enabled else "invalid token"
            logger.warning(f"MQTT auth: scanner {username[:8]}... rejected ({reason})")
            return HttpResponse(status=403)
    except Scanner.DoesNotExist:
        pass

    # Try user MQTT credentials
    try:
        creds = UserMQTTCredentials.objects.select_related('user').get(mqtt_id=username)
        if creds.user.is_active and creds.auth_token == password:
            logger.info(f"MQTT auth: user {creds.user.username} ({username[:8]}...) authenticated")
            return HttpResponse(status=200)
        else:
            reason = "user inactive" if not creds.user.is_active else "invalid token"
            logger.warning(f"MQTT auth: user {username[:8]}... rejected ({reason})")
            return HttpResponse(status=403)
    except UserMQTTCredentials.DoesNotExist:
        pass

    logger.warning(f"MQTT auth: unknown client {username[:8] if len(username) >= 8 else username}...")
    return HttpResponse(status=403)


@csrf_exempt
@api_view(['POST'])
@permission_classes([AllowAny])
def mqtt_acl(request):
    """Check MQTT topic ACLs.

    Called by mosquitto-go-auth plugin to validate publish/subscribe permissions.

    Expected POST data (form-encoded):
    - username: UUID (scanner or frontend client)
    - topic: MQTT topic being accessed
    - acc: Access type (1=subscribe, 2=publish)

    Returns:
    - 200 OK: Access allowed
    - 403 Forbidden: Access denied
    """
    username = request.data.get('username', '')
    topic = request.data.get('topic', '')
    acc = request.data.get('acc', '1')  # 1=sub, 2=pub

    logger.debug(f"MQTT ACL check: user={username}, topic={topic}, acc={acc}")

    topic_prefix = 'spectrum'

    # mosquitto-go-auth access types:
    # 1 = read, 2 = write, 3 = readwrite, 4 = subscribe, 5 = unsubscribe
    # acc can come as string or int depending on how it's sent
    acc_str = str(acc)
    is_subscribe = acc_str in ('1', '4')  # read or subscribe
    is_publish = acc_str == '2'

    # Check if this is the bridge service
    from django.conf import settings
    bridge_username = getattr(settings, 'MQTT_BRIDGE_USERNAME', '')
    if bridge_username and username == bridge_username:
        # Bridge can subscribe to scanner topics (to receive scans)
        if is_subscribe and topic.startswith(f"{topic_prefix}/scanners/"):
            logger.debug(f"MQTT ACL: bridge service subscribe to {topic} allowed")
            return HttpResponse(status=200)
        # Bridge can publish to timeline topics (to notify frontend of stored scans)
        if is_publish and topic.startswith(f"{topic_prefix}/scanners/") and topic.endswith("/timeline"):
            logger.debug(f"MQTT ACL: bridge service publish to {topic} allowed")
            return HttpResponse(status=200)
        # Bridge can publish to command topics (to control scanners from API)
        if is_publish and topic.startswith(f"{topic_prefix}/commands/"):
            logger.debug(f"MQTT ACL: bridge service publish to {topic} allowed")
            return HttpResponse(status=200)
        logger.warning(f"MQTT ACL: bridge service access to {topic} (acc={acc}) denied")
        return HttpResponse(status=403)

    # Check if this is a user
    try:
        from uuid import UUID
        mqtt_uuid = UUID(username)
        is_user = UserMQTTCredentials.objects.filter(mqtt_id=mqtt_uuid).exists()
        logger.debug(f"MQTT ACL: UUID lookup for {username}: is_user={is_user}")
        if is_user:
            # Users can subscribe to all topics
            if is_subscribe:
                logger.debug(f"MQTT ACL: user {username[:8]}... subscribe to {topic} allowed")
                return HttpResponse(status=200)
            # Users can publish to command topics (to control scanners)
            if is_publish and f"{topic_prefix}/commands/" in topic:
                logger.debug(f"MQTT ACL: user {username[:8]}... publish to {topic} allowed")
                return HttpResponse(status=200)
            logger.debug(f"MQTT ACL: user {username[:8]}... publish to {topic} denied")
            return HttpResponse(status=403)
    except (ValueError, TypeError) as e:
        logger.debug(f"MQTT ACL: UUID parse error for {username}: {e}")

    # Check if this is a scanner
    try:
        is_scanner = Scanner.objects.filter(id=username).exists()
    except Exception:
        is_scanner = False

    if is_scanner:
        # Scanners can:
        # - Publish to their own topics: spectrum/scanners/{their-uuid}/#
        # - Subscribe to command topics: spectrum/commands/{their-uuid}/#
        scanner_topic_prefix = f"{topic_prefix}/scanners/{username}/"
        command_topic_prefix = f"{topic_prefix}/commands/{username}/"

        if is_publish:
            if topic.startswith(scanner_topic_prefix):
                logger.debug(f"MQTT ACL: scanner {username[:8]}... publish to {topic} allowed")
                return HttpResponse(status=200)
        elif is_subscribe:
            if topic.startswith(command_topic_prefix) or topic.startswith(scanner_topic_prefix):
                logger.debug(f"MQTT ACL: scanner {username[:8]}... subscribe to {topic} allowed")
                return HttpResponse(status=200)

    logger.warning(f"MQTT ACL: {username[:8]}... access to {topic} (acc={acc}) denied")
    return HttpResponse(status=403)


@csrf_exempt
@api_view(['POST'])
@permission_classes([AllowAny])
def mqtt_superuser(request):
    """Check if user is MQTT superuser.

    Called by mosquitto-go-auth plugin. We don't use superusers.

    Returns:
    - 403 Forbidden: No superusers
    """
    return HttpResponse(status=403)


@api_view(['GET'])
def mqtt_credentials(request):
    """Get MQTT credentials for the current user.

    Returns the user's MQTT credentials, creating them if they don't exist.
    User must be authenticated.
    """
    if not request.user.is_authenticated:
        return Response({'error': 'Authentication required'}, status=status.HTTP_401_UNAUTHORIZED)

    # Get or create MQTT credentials for this user
    creds, created = UserMQTTCredentials.objects.get_or_create(user=request.user)
    if created:
        logger.info(f"Created MQTT credentials for user {request.user.username}")

    return Response({
        'username': str(creds.mqtt_id),
        'password': creds.auth_token,
    })


@api_view(['GET'])
@permission_classes([AllowAny])
def auth_user(request):
    """Get current authenticated user info.

    Also ensures CSRF cookie is set for subsequent requests.
    """
    from django.middleware.csrf import get_token
    # Ensure CSRF cookie is set
    get_token(request)

    if request.user.is_authenticated:
        return Response({
            'id': request.user.id,
            'username': request.user.username,
            'email': request.user.email,
            'is_staff': request.user.is_staff,
            'readonly': request.session.get('readonly', False),
            'share_label': request.session.get('share_label'),
        })
    return Response({'user': None}, status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([AllowAny])
def auth_login(request):
    """Login with username and password."""
    username = request.data.get('username')
    password = request.data.get('password')

    if not username or not password:
        return Response(
            {'error': 'Username and password required'},
            status=status.HTTP_400_BAD_REQUEST
        )

    user = authenticate(request, username=username, password=password)
    if user is not None:
        login(request, user)
        logger.info(f"User {username} logged in")
        return Response({
            'id': user.id,
            'username': user.username,
            'email': user.email,
            'is_staff': user.is_staff,
        })
    else:
        logger.warning(f"Failed login attempt for {username}")
        return Response(
            {'error': 'Invalid credentials'},
            status=status.HTTP_401_UNAUTHORIZED
        )


@api_view(['POST'])
@permission_classes([AllowAny])
def auth_logout(request):
    """Logout current user."""
    if request.user.is_authenticated:
        logger.info(f"User {request.user.username} logged out")
    logout(request)
    return Response({'status': 'logged out'})


# ============== Scanner Groups ==============


class ScannerGroupViewSet(viewsets.ModelViewSet):
    """API endpoint for scanner groups."""

    queryset = ScannerGroup.objects.all()
    serializer_class = ScannerGroupSerializer
    permission_classes = [IsAuthenticated, ReadOnlyIfShareSession]

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return ScannerGroupDetailSerializer
        return ScannerGroupSerializer

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=True, methods=['post'])
    def assign(self, request, pk=None):
        """Assign scanners to this group.

        POST data: {"scanners": ["uuid1", "uuid2", ...]}
        """
        group = self.get_object()
        scanner_ids = request.data.get('scanners', [])
        scanners = Scanner.objects.filter(id__in=scanner_ids)
        group.scanners.add(*scanners)
        return Response({'status': 'assigned', 'count': scanners.count()})

    @action(detail=True, methods=['post'])
    def release(self, request, pk=None):
        """Remove scanners from this group.

        POST data: {"scanners": ["uuid1", "uuid2", ...]}
        """
        group = self.get_object()
        scanner_ids = request.data.get('scanners', [])
        scanners = Scanner.objects.filter(id__in=scanner_ids)
        group.scanners.remove(*scanners)
        return Response({'status': 'released', 'count': scanners.count()})


# ============== Access Management ==============


@api_view(['GET'])
def list_access(request):
    """List access grants. Staff sees all, users see their own."""
    if request.user.is_staff:
        grants = Access.objects.select_related('user', 'scanner_group', 'scanner').all()
    else:
        grants = Access.objects.select_related('user', 'scanner_group', 'scanner').filter(user=request.user)
    return Response(AccessSerializer(grants, many=True).data)


@api_view(['POST'])
def create_access(request):
    """Create a new access grant (staff only).

    POST data:
    - type: "user" or "token"
    - user_id: (if type=user) user PK
    - group_id: (if scoped to a scanner group) group UUID
    - scanner_id: (if scoped to scanner) scanner UUID
    - permission: "r" or "rw" (default "r")
    - label: descriptive label
    - expires_hours: optional expiration in hours
    """
    if not request.user.is_staff:
        return Response({'error': 'Admin access required'}, status=status.HTTP_403_FORBIDDEN)

    access_type = request.data.get('type', 'token')
    permission = request.data.get('permission', 'r')
    label = request.data.get('label', '')

    kwargs = {
        'permission': permission,
        'label': label,
        'created_by': request.user,
    }

    # Principal
    if access_type == 'user':
        user_id = request.data.get('user_id')
        if not user_id:
            return Response({'error': 'user_id required for type=user'}, status=status.HTTP_400_BAD_REQUEST)
        from django.contrib.auth.models import User as AuthUser
        try:
            kwargs['user'] = AuthUser.objects.get(pk=user_id)
        except AuthUser.DoesNotExist:
            return Response({'error': 'User not found'}, status=status.HTTP_404_NOT_FOUND)
    else:
        from core.models import generate_auth_token
        kwargs['token'] = generate_auth_token()

    # Scope
    group_id = request.data.get('group_id')
    scanner_id = request.data.get('scanner_id')
    if group_id:
        try:
            kwargs['scanner_group'] = ScannerGroup.objects.get(pk=group_id)
        except ScannerGroup.DoesNotExist:
            return Response({'error': 'Scanner group not found'}, status=status.HTTP_404_NOT_FOUND)
    elif scanner_id:
        try:
            kwargs['scanner'] = Scanner.objects.get(pk=scanner_id)
        except Scanner.DoesNotExist:
            return Response({'error': 'Scanner not found'}, status=status.HTTP_404_NOT_FOUND)
    else:
        return Response({'error': 'group_id or scanner_id required'}, status=status.HTTP_400_BAD_REQUEST)

    # Expiration
    expires_hours = request.data.get('expires_hours')
    if expires_hours:
        kwargs['expires_at'] = timezone.now() + timedelta(hours=int(expires_hours))

    access = Access.objects.create(**kwargs)
    return Response(AccessSerializer(access).data, status=status.HTTP_201_CREATED)


@api_view(['DELETE'])
def revoke_access(request, pk):
    """Revoke an access grant (staff only)."""
    if not request.user.is_staff:
        return Response({'error': 'Admin access required'}, status=status.HTTP_403_FORBIDDEN)
    try:
        access = Access.objects.get(pk=pk)
    except Access.DoesNotExist:
        return Response({'error': 'Not found'}, status=status.HTTP_404_NOT_FOUND)
    access.is_active = False
    access.save(update_fields=['is_active', 'updated_at'])
    return Response({'status': 'revoked'})


# ============== Share Link System ==============

from django.contrib.auth.models import User
from django.shortcuts import redirect
from core.models import ShareLink


@api_view(['GET'])
@permission_classes([AllowAny])
def share_token_auth(request, token):
    """Authenticate via share token and redirect to app.

    Checks Access model first (new), then falls back to ShareLink (legacy).
    """
    # Try Access token first
    try:
        access = Access.objects.select_related('scanner_group', 'scanner').get(token=token)
        if access.is_valid():
            # Get or create demo user
            demo_user, created = User.objects.get_or_create(
                username='demo_viewer',
                defaults={'email': 'demo@example.com', 'is_active': True, 'is_staff': False}
            )
            if created:
                demo_user.set_unusable_password()
                demo_user.save()

            login(request, demo_user, backend='django.contrib.auth.backends.ModelBackend')
            request.session['readonly'] = access.permission == 'r'
            request.session['access_id'] = str(access.id)
            request.session['share_label'] = access.label

            access.record_use()
            logger.info(f"Access token login: {access.label} (use #{access.use_count})")

            from django.conf import settings
            if settings.DEBUG:
                return redirect('http://localhost:5173/')
            return redirect('/')

        reason = "revoked" if not access.is_active else "expired"
        logger.warning(f"Access token {reason}: {access.label}")
        return Response({'error': f'Access token has been {reason}'}, status=status.HTTP_401_UNAUTHORIZED)
    except Access.DoesNotExist:
        pass

    # Fall back to legacy ShareLink
    try:
        share_link = ShareLink.objects.get(token=token)
    except ShareLink.DoesNotExist:
        logger.warning(f"Share link not found: {token[:20]}...")
        return Response(
            {'error': 'Invalid share link'},
            status=status.HTTP_401_UNAUTHORIZED
        )

    if not share_link.is_valid():
        reason = "revoked" if not share_link.is_active else "expired"
        logger.warning(f"Share link {reason}: {share_link.label}")
        return Response(
            {'error': f'Share link has been {reason}'},
            status=status.HTTP_401_UNAUTHORIZED
        )

    # Get or create the demo user
    demo_user, created = User.objects.get_or_create(
        username='demo_viewer',
        defaults={
            'email': 'demo@example.com',
            'is_active': True,
            'is_staff': False,
        }
    )
    if created:
        # Set unusable password - can't login normally
        demo_user.set_unusable_password()
        demo_user.save()
        logger.info("Created demo_viewer user for share links")

    # Log in as demo user
    login(request, demo_user, backend='django.contrib.auth.backends.ModelBackend')

    # Mark session as read-only
    request.session['readonly'] = True
    request.session['share_label'] = share_link.label

    # Record usage
    share_link.record_use()

    logger.info(f"Share link login: {share_link.label} (use #{share_link.use_count})")

    # Redirect to frontend (different URL in dev vs production)
    from django.conf import settings
    if settings.DEBUG:
        return redirect('http://localhost:5173/')
    return redirect('/')


@api_view(['POST'])
def generate_share_link(request):
    """Generate a new share link (admin only).

    POST data:
    - expires_hours: Optional expiration in hours
    - label: Label to identify this link (required)
    """
    if not request.user.is_staff:
        return Response(
            {'error': 'Admin access required'},
            status=status.HTTP_403_FORBIDDEN
        )

    label = request.data.get('label')
    if not label:
        return Response(
            {'error': 'label is required'},
            status=status.HTTP_400_BAD_REQUEST
        )

    expires_hours = request.data.get('expires_hours')
    expires_at = None

    if expires_hours:
        try:
            expires_hours = int(expires_hours)
            expires_at = timezone.now() + timedelta(hours=expires_hours)
        except ValueError:
            return Response(
                {'error': 'expires_hours must be a number'},
                status=status.HTTP_400_BAD_REQUEST
            )

    # Create the share link in the database
    share_link = ShareLink.objects.create(
        label=label,
        expires_at=expires_at,
        created_by=request.user,
    )

    # Build the full URL
    share_url = request.build_absolute_uri(f'/share/{share_link.token}')

    logger.info(f"Generated share link: {label} (expires: {expires_hours or 'never'}h)")

    return Response({
        'id': share_link.id,
        'token': share_link.token,
        'url': share_url,
        'label': label,
        'expires_at': share_link.expires_at,
        'created_at': share_link.created_at,
    })
