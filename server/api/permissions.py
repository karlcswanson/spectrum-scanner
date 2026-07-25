"""DRF permission classes for object-level access control."""

from django.db.models import Q
from django.utils import timezone
from rest_framework.permissions import BasePermission, SAFE_METHODS

from core.models import Access, Scanner


def get_active_grants(user):
    """Get active, non-expired access grants for a user."""
    return Access.objects.filter(
        user=user,
        is_active=True,
    ).filter(
        Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now())
    )


def get_accessible_scanner_ids(user):
    """Get set of scanner IDs a non-staff user can access."""
    grants = get_active_grants(user)

    # Direct scanner grants
    scanner_ids = set(
        grants.filter(scanner__isnull=False)
        .values_list('scanner_id', flat=True)
    )

    # Scanners via group grants
    group_ids = list(
        grants.filter(scanner_group__isnull=False)
        .values_list('scanner_group_id', flat=True)
    )
    if group_ids:
        group_scanner_ids = Scanner.objects.filter(
            scanner_groups__id__in=group_ids
        ).values_list('id', flat=True)
        scanner_ids.update(group_scanner_ids)

    return scanner_ids


def get_accessible_group_ids(user):
    """Get set of group IDs a non-staff user can access."""
    grants = get_active_grants(user)
    return set(
        grants.filter(scanner_group__isnull=False)
        .values_list('scanner_group_id', flat=True)
    )


def get_rw_scanner_ids(user):
    """Scanner IDs a non-staff user has read/write on (direct grant or via a
    group grant)."""
    grants = get_active_grants(user).filter(permission='rw')
    scanner_ids = set(
        grants.filter(scanner__isnull=False).values_list('scanner_id', flat=True)
    )
    group_ids = list(
        grants.filter(scanner_group__isnull=False).values_list('scanner_group_id', flat=True)
    )
    if group_ids:
        scanner_ids.update(
            Scanner.objects.filter(scanner_groups__id__in=group_ids).values_list('id', flat=True)
        )
    return scanner_ids


def can_write_monitored_frequency(request, freq):
    """Whether the request may edit/delete a monitored frequency.

    Mirrors the scanner write model: staff -> any; otherwise the user needs rw
    on a scanner (or group) the frequency is scoped to. Global frequencies (no
    scanner/group scope) are staff-only, since they apply to everything.
    """
    user = request.user
    if getattr(user, 'is_staff', False):
        return True

    scanner_ids = set(freq.scanners.values_list('id', flat=True))
    group_ids = set(freq.groups.values_list('id', flat=True))
    if not scanner_ids and not group_ids:
        return False  # global -> staff only

    if scanner_ids & get_rw_scanner_ids(user):
        return True
    if group_ids:
        rw_group_ids = set(
            get_active_grants(user)
            .filter(permission='rw', scanner_group__isnull=False)
            .values_list('scanner_group_id', flat=True)
        )
        if group_ids & rw_group_ids:
            return True
    return False


def _grant_scanner_ids(grant):
    """Scanner IDs covered by a single Access grant (direct or via its group)."""
    ids = set()
    if grant.scanner_id:
        ids.add(grant.scanner_id)
    if grant.scanner_group_id:
        ids.update(
            Scanner.objects.filter(scanner_groups__id=grant.scanner_group_id)
            .values_list('id', flat=True)
        )
    return ids


def get_request_scanner_ids(request):
    """Scanner IDs a request may read, or ``None`` for unrestricted.

    Unlike ``get_accessible_scanner_ids`` (which only looks at a user's own
    Access grants), this is request-aware so it works for share-link sessions,
    where every visitor is the same ``demo_viewer`` user and the scope lives on
    the session's ``access_id`` instead:

    - staff -> None (all scanners)
    - legacy ShareLink session (readonly, no access_id) -> None (global demo)
    - otherwise -> the user's active grants, plus the share session's
      ``access_id`` grant if present.
    """
    user = request.user
    if getattr(user, 'is_staff', False):
        return None

    ids = set(get_accessible_scanner_ids(user))

    access_id = request.session.get('access_id')
    if access_id:
        try:
            grant = Access.objects.get(pk=access_id, is_active=True)
            if grant.is_valid():
                ids |= _grant_scanner_ids(grant)
        except Access.DoesNotExist:
            pass
    elif request.session.get('readonly'):
        # Legacy ShareLink: intentional global read-only demo access.
        return None

    return ids


# Read-only share sessions are limited to this recent window. The public demo
# is a live view; barring anonymous viewers from deep/arbitrary-range history
# keeps the expensive DB scans unreachable without a real login, and collapses
# every share viewer onto one small, always-warm cache window per band.
READONLY_MAX_HISTORY_SECONDS = 600  # 10 minutes


def get_request_max_history_seconds(request):
    """How far back this request may query, or ``None`` for unlimited.

    Read-only share sessions (legacy ShareLink and read Access shares — both set
    the ``readonly`` session flag) are capped to a short live window. Full
    logins (staff, regular users, rw shares) are unrestricted.
    """
    session = getattr(request, 'session', None)
    if session is not None and session.get('readonly'):
        return READONLY_MAX_HISTORY_SECONDS
    return None


class ReadOnlyIfShareSession(BasePermission):
    """Block write operations for share-link sessions."""

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True
        if request.session.get('readonly'):
            return False
        return True


class HasScannerAccess(BasePermission):
    """Object-level permission for Scanner instances.

    - Staff: full access
    - Non-staff read: requires any active grant (r or rw) for this scanner
    - Non-staff write: requires rw grant for this scanner
    """

    def has_object_permission(self, request, view, obj):
        if request.user.is_staff:
            return True

        # Reads: request-aware so share-link sessions (demo_viewer with no grants
        # of its own, scope on the session access_id) can read granted scanners.
        # None means unrestricted (staff handled above / legacy global share).
        if request.method in SAFE_METHODS:
            allowed = get_request_scanner_ids(request)
            return allowed is None or obj.id in allowed

        # Write: require an rw grant for this user. Share sessions never reach
        # here (ReadOnlyIfShareSession blocks unsafe methods first).
        grants = get_active_grants(request.user)
        scanner_group_ids = obj.scanner_groups.values_list('id', flat=True)
        return (
            grants.filter(scanner=obj, permission='rw').exists() or
            grants.filter(scanner_group_id__in=scanner_group_ids, permission='rw').exists()
        )


class HasScannerGroupAccess(BasePermission):
    """Object-level permission for ScannerGroup instances.

    - Staff: full access
    - Non-staff read: requires any active grant for this group
    - Non-staff write: requires rw grant for this group
    """

    def has_object_permission(self, request, view, obj):
        if request.user.is_staff:
            return True

        grants = get_active_grants(request.user).filter(scanner_group=obj)

        if request.method in SAFE_METHODS:
            return grants.exists()

        return grants.filter(permission='rw').exists()


class IsStaffOrReadOnly(BasePermission):
    """Allow staff full access, everyone else read-only."""

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True
        return request.user.is_staff


class CanWriteMonitoredFrequency(BasePermission):
    """Object-level write permission for monitored frequencies (create is scope-
    checked in the view). Reads pass; writes need write access to the freq's
    scope (see ``can_write_monitored_frequency``)."""

    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return True
        return can_write_monitored_frequency(request, obj)
