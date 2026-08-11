"""Baseline-access signals.

Read-all is expressed the standard Django way: a **default group** holds the
``view_scanner`` model permission, and every user is a member. `request_reads_all`
(api/permissions.py) checks `user.has_perm('core.view_scanner')`.

- ``ensure_default_group`` (post_migrate) makes sure the group exists and holds
  ``view_scanner``. It runs when model permissions are guaranteed to exist.
- ``add_user_to_default_group`` (post_save on User) adds each newly-created user
  to the group — on create only, so an admin can later remove someone without it
  being re-added.

Turn the baseline off by removing ``view_scanner`` from the group in the admin
(auditable/revocable), or set ``DEFAULT_USER_GROUP=''`` to stop auto-adding new
users. Share/demo users are still scoped at request time, so their membership is
harmless.
"""

import logging

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db.models.signals import post_migrate, post_save

logger = logging.getLogger('api')


def _default_group_name():
    return getattr(settings, 'DEFAULT_USER_GROUP', '') or ''


def ensure_default_group(sender, **kwargs):
    """Ensure the default group exists and grants baseline read (view_scanner)."""
    name = _default_group_name()
    if not name:
        return
    from django.contrib.auth.models import Group, Permission
    try:
        perm = Permission.objects.get(
            content_type__app_label='core', codename='view_scanner'
        )
    except Permission.DoesNotExist:
        return  # this app's permissions aren't created yet on this pass
    group, created = Group.objects.get_or_create(name=name)
    group.permissions.add(perm)
    if created:
        logger.info("Created default access group %r with view_scanner", name)


def add_user_to_default_group(sender, instance, created, **kwargs):
    """Add each newly-created user to the default (baseline-read) group."""
    if not created:
        return
    name = _default_group_name()
    if not name:
        return
    from django.contrib.auth.models import Group
    group = Group.objects.filter(name=name).first()
    if group:
        instance.groups.add(group)


def connect_signals():
    post_migrate.connect(ensure_default_group, dispatch_uid='core.ensure_default_group')
    post_save.connect(
        add_user_to_default_group,
        sender=get_user_model(),
        dispatch_uid='core.add_user_to_default_group',
    )
