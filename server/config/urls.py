"""URL configuration for Spectrum Server."""

from django.contrib import admin
from django.urls import path, include

from api.views import share_token_auth

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include('api.urls')),
    # Share link authentication (at root for cleaner URLs)
    path('share/<str:token>', share_token_auth, name='share-auth'),
]
