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
    if not instance.user_id:
        return
    _dispatch(_do_user_sync, instance.user_id)


def on_access_delete(sender, instance, **kwargs):
    if not instance.user_id:
        return
    _dispatch(_do_user_sync, instance.user_id)


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
