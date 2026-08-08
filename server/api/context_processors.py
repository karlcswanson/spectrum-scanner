"""Template context processors."""
from django.conf import settings


def analytics_embed(request):
    """Expose ANALYTICS_EMBED to templates (admin head injection).

    Same env var the Vue SPA injects at container startup (frontend/publish.sh),
    so one setting covers both the Django-admin and Vue sides.
    """
    return {'ANALYTICS_EMBED': settings.ANALYTICS_EMBED}


def sso(request):
    """Expose enterprise-SSO login state to templates (admin login button).

    Mirrors what /api/auth/user/ hands the Vue SPA, so the admin and SPA login
    surfaces theme from the same SSO_* settings. All keys are safe when SSO is
    off (enabled=False), so the admin template just renders nothing.
    """
    enabled = settings.SSO_ENABLED
    backend_name = getattr(settings, 'SSO_BACKEND_NAME', '') if enabled else ''
    return {
        'sso_enabled': enabled,
        'sso_label': getattr(settings, 'SSO_BUTTON_LABEL', 'Sign in with SSO'),
        'sso_brand': getattr(settings, 'SSO_PROVIDER_BRAND', 'generic'),
        'sso_login_url': f'/oauth/login/{backend_name}/' if backend_name else '',
    }
