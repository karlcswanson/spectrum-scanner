"""URL configuration for Spectrum Server."""

from django.conf import settings
from django.contrib import admin
from django.urls import path, include

from api.views import share_token_auth

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include('api.urls')),
    # Share link authentication (at root for cleaner URLs)
    path('share/<str:token>', share_token_auth, name='share-auth'),
]

# Enterprise SSO login/callback routes, only when opted in (settings.SSO_ENABLED).
# python-social-auth provides /oauth/login/<backend>/ and /oauth/complete/<backend>/.
if settings.SSO_ENABLED:
    urlpatterns += [path('oauth/', include('social_django.urls', namespace='social'))]
    # Add the SSO button to the Django admin login page. The custom template
    # extends the stock admin/login.html (different filename, so no recursion)
    # and injects the button above the form via the `sso` context processor.
    admin.site.login_template = 'admin/sso_login.html'
