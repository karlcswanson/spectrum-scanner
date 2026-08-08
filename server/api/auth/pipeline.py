"""Custom python-social-auth pipeline steps.

Only referenced when SSO is enabled (see SOCIAL_AUTH_PIPELINE in settings).
"""

import logging

from django.conf import settings

logger = logging.getLogger('api')


def assign_default_groups(backend, user, response, *args, **kwargs):
    """Add newly-created SSO users to the local Django groups in
    SSO_DEFAULT_GROUPS.

    These are LOCAL groups managed in the app (not synced from the identity
    provider) — they carry the baseline access, via Access grants assigned to
    the group. Runs only on first login (`is_new`) so an admin can later remove
    a user from the default group without it being re-added on every sign-in.
    """
    if not kwargs.get('is_new'):
        return

    names = getattr(settings, 'SSO_DEFAULT_GROUPS', [])
    if not names:
        return

    from django.contrib.auth.models import Group

    for name in names:
        group, _ = Group.objects.get_or_create(name=name)
        user.groups.add(group)
    logger.info("Assigned new SSO user %s to default groups %s", user, names)
