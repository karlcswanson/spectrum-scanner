"""
ASGI config for Spectrum Server.

Frontend connects directly to MQTT for real-time scan data.
This ASGI app serves the Django REST API only.
"""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

application = get_asgi_application()
