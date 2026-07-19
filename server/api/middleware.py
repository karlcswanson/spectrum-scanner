"""Analytics embed injection for Django-rendered HTML.

The Vue SPA gets the tracker snippet injected into its index.html at frontend
container startup (frontend/publish.sh). This middleware does the same for pages
Django renders itself, from the SAME `ANALYTICS_EMBED` setting — so one env var
covers both sides. No-op when the setting is unset (the middleware removes itself
from the chain), when the response isn't HTML, or on internal /admin//static/.
"""
from django.conf import settings
from django.core.exceptions import MiddlewareNotUsed


class AnalyticsEmbedMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        self.snippet = (getattr(settings, 'ANALYTICS_EMBED', '') or '').strip()
        if not self.snippet:
            # Nothing to inject — drop out entirely (zero per-request overhead).
            raise MiddlewareNotUsed()

    def __call__(self, request):
        response = self.get_response(request)

        if getattr(response, 'streaming', False):
            return response
        if 'text/html' not in response.get('Content-Type', ''):
            return response
        # Don't track internal tooling. Remove these prefixes to include admin.
        if request.path.startswith(('/admin/', '/static/')):
            return response

        try:
            body = response.content.decode(response.charset)
        except (AttributeError, UnicodeDecodeError, LookupError):
            return response
        if '</head>' not in body:
            return response

        response.content = body.replace('</head>', self.snippet + '</head>', 1).encode(response.charset)
        if response.has_header('Content-Length'):
            response['Content-Length'] = str(len(response.content))
        return response
