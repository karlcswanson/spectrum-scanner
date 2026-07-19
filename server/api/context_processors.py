"""Template context processors."""
from django.conf import settings


def analytics_embed(request):
    """Expose ANALYTICS_EMBED to templates (admin head injection).

    Same env var the Vue SPA injects at container startup (frontend/publish.sh),
    so one setting covers both the Django-admin and Vue sides.
    """
    return {'ANALYTICS_EMBED': settings.ANALYTICS_EMBED}
