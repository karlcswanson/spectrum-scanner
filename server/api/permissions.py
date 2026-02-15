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

        grants = get_active_grants(request.user)

        # Check direct scanner grant
        scanner_grants = grants.filter(scanner=obj)

        # Check group grants (any group this scanner belongs to)
        scanner_group_ids = obj.scanner_groups.values_list('id', flat=True)
        group_grants = grants.filter(scanner_group_id__in=scanner_group_ids)

        if request.method in SAFE_METHODS:
            return scanner_grants.exists() or group_grants.exists()

        # Write: require rw permission
        return (
            scanner_grants.filter(permission='rw').exists() or
            group_grants.filter(permission='rw').exists()
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
