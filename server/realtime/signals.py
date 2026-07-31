"""Django signals for auto-syncing Mosquitto Dynamic Security state.

All signal handlers dispatch dynsec work to a background thread so they
never block Django request handling. Failures are logged — the dynsec_sync
management command is the recovery path.
"""

import logging
import threading
from concurrent.futures import ThreadPoolExecutor

from django.db.models.signals import post_save, post_delete, m2m_changed

from core.models import Scanner, Access

logger = logging.getLogger(__name__)

# Single-thread executor serialises dynsec calls and keeps them off the
# request thread.  Daemon thread so it doesn't prevent shutdown.
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='dynsec')


def _dispatch(fn, *args, **kwargs):
    """Submit work to the background executor, logging any errors."""
    from django.conf import settings
    if getattr(settings, 'TESTING', False):
        # No broker in the test env, and the background thread's DB connection
        # otherwise blocks test-database teardown.
        return

    def _wrapper():
        try:
            fn(*args, **kwargs)
        except Exception as e:
            logger.error(f'DynSec background task failed: {e}')
    _executor.submit(_wrapper)


def _get_dynsec():
    from realtime.dynsec import get_dynsec_client
    return get_dynsec_client()


# ── Background work functions (run in executor) ──

def _do_scanner_sync(scanner_id, update_password=False):
    from realtime.dynsec import ensure_scanner_roles
    scanner = Scanner.objects.get(pk=scanner_id)
    dynsec = _get_dynsec()
    ensure_scanner_roles(dynsec, scanner, update_password=update_password)
    logger.info(f'DynSec: synced scanner {scanner.name} ({scanner.id})')


def _do_scanner_delete(scanner_id):
    from realtime.dynsec import delete_scanner_roles
    dynsec = _get_dynsec()
    delete_scanner_roles(dynsec, str(scanner_id))
    logger.info(f'DynSec: deleted scanner roles for {scanner_id}')


def _do_user_sync(user_id):
    from django.contrib.auth.models import User
    from realtime.dynsec import sync_user_roles
    user = User.objects.get(pk=user_id)
    dynsec = _get_dynsec()
    sync_user_roles(user, dynsec)
    logger.info(f'DynSec: synced roles for {user.username}')


def _do_group_change(group_ids, scanner_ids_to_sync=None):
    """Sync scanner roles and all affected users for the given groups."""
    from realtime.dynsec import sync_user_roles, ensure_scanner_roles
    dynsec = _get_dynsec()

    if scanner_ids_to_sync:
        for scanner in Scanner.objects.filter(pk__in=scanner_ids_to_sync):
            ensure_scanner_roles(dynsec, scanner)

    users = set()
    for grant in Access.objects.filter(
        scanner_group_id__in=group_ids,
        user__isnull=False,
        is_active=True,
    ).select_related('user'):
        users.add(grant.user)

    for user in users:
        try:
            sync_user_roles(user, dynsec)
            logger.info(f'DynSec: synced {user.username} after group change')
        except Exception as e:
            logger.error(f'DynSec: failed to sync {user.username} after group change: {e}')


def _do_group_clear_sync():
    """After a clear, re-sync all users who have any group-scoped grants."""
    from core.models import UserMQTTCredentials
    from realtime.dynsec import sync_user_roles
    dynsec = _get_dynsec()

    for creds in UserMQTTCredentials.objects.select_related('user').all():
        if Access.objects.filter(
            user=creds.user,
            scanner_group__isnull=False,
            is_active=True,
        ).exists():
            try:
                sync_user_roles(creds.user, dynsec)
            except Exception as e:
                logger.error(f'DynSec: failed to sync {creds.user.username} after clear: {e}')


def _do_access_group_sync(group_id):
    """Re-sync broker roles for every member of a Django auth Group.

    A group-principal Access grant applies to all users in the group (see
    permissions.get_active_grants), so creating/revoking such a grant must
    resync each member's dynsec roles.  Only users with MQTT credentials have
    a broker client to update.
    """
    from django.contrib.auth.models import Group
    from core.models import UserMQTTCredentials
    from realtime.dynsec import sync_user_roles
    dynsec = _get_dynsec()

    try:
        group = Group.objects.get(pk=group_id)
    except Group.DoesNotExist:
        return

    member_ids = set(group.user_set.values_list('pk', flat=True))
    for creds in UserMQTTCredentials.objects.filter(
        user_id__in=member_ids,
    ).select_related('user'):
        try:
            sync_user_roles(creds.user, dynsec)
            logger.info(f'DynSec: synced {creds.user.username} after group grant change')
        except Exception as e:
            logger.error(f'DynSec: failed to sync {creds.user.username} after group grant change: {e}')


def _do_all_creds_sync():
    """Re-sync every user with a broker client.

    Fallback for a User.groups clear on the group side, where the removed
    member PKs aren't available from the m2m signal.
    """
    from core.models import UserMQTTCredentials
    from realtime.dynsec import sync_user_roles
    dynsec = _get_dynsec()

    for creds in UserMQTTCredentials.objects.select_related('user').all():
        try:
            sync_user_roles(creds.user, dynsec)
        except Exception as e:
            logger.error(f'DynSec: failed to sync {creds.user.username}: {e}')


# ── Signal handlers (dispatch to background) ──

def on_scanner_save(sender, instance, created, **kwargs):
    update_fields = kwargs.get('update_fields')
    if update_fields is not None:
        STATUS_FIELDS = {'online', 'last_seen', 'scanning', 'current_band'}
        if set(update_fields) <= STATUS_FIELDS:
            return
    password_changed = update_fields is not None and 'auth_token' in update_fields
    _dispatch(_do_scanner_sync, instance.pk, update_password=password_changed or created)


def on_scanner_delete(sender, instance, **kwargs):
    _dispatch(_do_scanner_delete, instance.pk)


def on_access_save(sender, instance, **kwargs):
    if instance.user_id:
        _dispatch(_do_user_sync, instance.user_id)
    elif instance.group_id:
        _dispatch(_do_access_group_sync, instance.group_id)


def on_access_delete(sender, instance, **kwargs):
    if instance.user_id:
        _dispatch(_do_user_sync, instance.user_id)
    elif instance.group_id:
        _dispatch(_do_access_group_sync, instance.group_id)


def on_user_save(sender, instance, **kwargs):
    from core.models import UserMQTTCredentials
    if not UserMQTTCredentials.objects.filter(user=instance).exists():
        return
    _dispatch(_do_user_sync, instance.pk)


def on_scanner_groups_changed(sender, instance, action, pk_set, reverse, **kwargs):
    if action not in ('post_add', 'post_remove', 'post_clear'):
        return

    if reverse:
        # instance is a ScannerGroup, pk_set is Scanner PKs
        group_ids = {instance.pk}
        scanner_ids = pk_set or set()
        _dispatch(_do_group_change, group_ids, scanner_ids)
    else:
        # instance is a Scanner, pk_set is ScannerGroup PKs
        group_ids = pk_set or set()
        scanner_ids = {instance.pk}

        if action == 'post_clear' or not group_ids:
            _dispatch(_do_scanner_sync, instance.pk)
            _dispatch(_do_group_clear_sync)
            return

        _dispatch(_do_group_change, group_ids, scanner_ids)


def on_user_groups_changed(sender, instance, action, pk_set, reverse, **kwargs):
    """Resync broker roles when a user's Django-group membership changes.

    Group-principal Access grants are inherited via auth-group membership, so
    adding/removing a user from a group must update that user's dynsec roles.
    """
    if action not in ('post_add', 'post_remove', 'post_clear'):
        return

    from core.models import UserMQTTCredentials

    if reverse:
        # instance is a Group; pk_set is the affected User PKs (None on clear).
        if action == 'post_clear' or pk_set is None:
            _dispatch(_do_all_creds_sync)
            return
        user_ids = pk_set
    else:
        # instance is a User; membership changed for this user regardless of
        # action (pk_set is None on clear, but the user is still `instance`).
        user_ids = {instance.pk}

    for uid in user_ids:
        if UserMQTTCredentials.objects.filter(user_id=uid).exists():
            _dispatch(_do_user_sync, uid)


def connect_signals():
    """Connect all dynsec signals. Called from AppConfig.ready()."""
    from django.contrib.auth.models import User

    post_save.connect(on_scanner_save, sender=Scanner)
    post_delete.connect(on_scanner_delete, sender=Scanner)
    post_save.connect(on_access_save, sender=Access)
    post_delete.connect(on_access_delete, sender=Access)
    post_save.connect(on_user_save, sender=User)
    m2m_changed.connect(
        on_scanner_groups_changed,
        sender=Scanner.scanner_groups.through,
    )
    m2m_changed.connect(
        on_user_groups_changed,
        sender=User.groups.through,
    )
