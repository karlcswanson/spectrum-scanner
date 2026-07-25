"""DRF throttle classes.

Share-link visitors all authenticate as a single ``demo_viewer`` Django user,
so the stock ``UserRateThrottle`` would collapse every visitor into one shared
bucket (and 429 them collectively). These throttles key on the session — each
browser/share visitor gets its own bucket — or the client IP.
"""

from rest_framework.throttling import AnonRateThrottle, SimpleRateThrottle


class SessionOrIPRateThrottle(SimpleRateThrottle):
    """General per-visitor API cap.

    Keys on the session when there is one (works even though all share visitors
    share the ``demo_viewer`` user), otherwise the client IP. Rate: ``session``.
    """

    scope = 'session'

    def get_cache_key(self, request, view):
        session_key = getattr(request.session, 'session_key', None)
        if session_key:
            ident = f'session:{session_key}'
        else:
            ident = f'ip:{self.get_ident(request)}'
        return self.cache_format % {'scope': self.scope, 'ident': ident}


class LoginRateThrottle(AnonRateThrottle):
    """IP-keyed throttle for the login endpoint (brute-force protection)."""

    scope = 'login'


class ShareAuthRateThrottle(AnonRateThrottle):
    """IP-keyed throttle for the share-token auth endpoint (session flood)."""

    scope = 'share_auth'
