"""
Django settings for Spectrum Server.
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.getenv('DJANGO_SECRET_KEY', 'dev-secret-key-change-in-production')

DEBUG = os.getenv('DEBUG', 'false').lower() == 'true'

# True while the Django test runner is active. Used to skip side effects that
# reach external services (e.g. the dynsec MQTT sync fired on model save).
TESTING = 'test' in sys.argv

ALLOWED_HOSTS = os.getenv('ALLOWED_HOSTS', 'localhost,127.0.0.1,server').split(',')

# Application definition
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    # Third party
    'rest_framework',
    'corsheaders',
    # Local apps
    'core',
    'api',
    'realtime',
]

MIDDLEWARE = [
    'django.middleware.gzip.GZipMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

# Optional analytics snippet. Injected into the admin <head> via the
# admin/base_site.html override (api.context_processors.analytics_embed). Same
# value as the frontend's ANALYTICS_EMBED (the Vue SPA injects it at container
# startup), so one env var covers both the Django-admin and Vue sides.
ANALYTICS_EMBED = os.getenv('ANALYTICS_EMBED', '')

# Branding (NetBox-style: config lives here in Django
# settings, the server is the single source of truth). Surfaced to the Vue SPA
# via the public /api/config/ endpoint (api.views.api_config). All fields
# optional. See docs/branding.md.
BRANDING = {
    'name': os.getenv('BRAND_NAME', ''),        # header / login display name
    'logo_url': os.getenv('BRAND_LOGO_URL', ''),  # header + login logo (URL or same-origin path)
    'accent': os.getenv('BRAND_ACCENT', ''),    # CSS colour: header accent + primary button
    'title': os.getenv('BRAND_TITLE', ''),      # browser tab title (verbatim override; default in index.html)
}

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'api.context_processors.analytics_embed',
                'api.context_processors.sso',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

# Database
_db_engine = os.getenv('DB_ENGINE', 'django.db.backends.sqlite3')

DATABASES = {
    'default': {
        'ENGINE': _db_engine,
        'NAME': os.getenv('DB_NAME', BASE_DIR / 'db.sqlite3'),
        'USER': os.getenv('DB_USER', ''),
        'PASSWORD': os.getenv('DB_PASSWORD', ''),
        'HOST': os.getenv('DB_HOST', ''),
        'PORT': os.getenv('DB_PORT', ''),
    }
}

if 'sqlite3' in _db_engine:
    DATABASES['default']['OPTIONS'] = {
        'timeout': 30,
        'init_command': (
            'PRAGMA journal_mode=WAL;'
            'PRAGMA synchronous=NORMAL;'
        ),
    }

# Persistent DB connections in production (Postgres). Without this every request
# opens and tears down a fresh connection — expensive under the demo's
# concurrency and wasteful now that the read path is cached. CONN_HEALTH_CHECKS
# revalidates a reused connection before use so a stale one can't 500 a request.
#
# Only when NOT DEBUG: production runs gunicorn with a *fixed* worker×thread
# pool, so persistent connections stay bounded. The dev `runserver` spawns an
# unbounded thread per request, and holding a connection per thread for
# CONN_MAX_AGE seconds exhausts Postgres ("too many clients"). Dev/SQLite/tests
# keep the default per-request connection.
if 'postgresql' in _db_engine and not DEBUG:
    DATABASES['default']['CONN_MAX_AGE'] = int(os.getenv('CONN_MAX_AGE', '60'))
    DATABASES['default']['CONN_HEALTH_CHECKS'] = True

# Safety net: cap how long any single query may run so a pathological one can't
# peg Postgres and hang the whole box (dev + prod). Normal queries finish in
# milliseconds; the rollup's largest batch is well under this. A timed-out
# query just errors that one request/cycle. Tune via env if needed.
if 'postgresql' in _db_engine:
    DATABASES['default'].setdefault('OPTIONS', {})
    DATABASES['default']['OPTIONS']['options'] = (
        f"-c statement_timeout={os.getenv('DB_STATEMENT_TIMEOUT_MS', '30000')}"
    )

# Cache — Redis (dev + prod) backs the read-API response cache and the
# single-flight locks that collapse a stampede of identical /history requests
# into one DB query. Falls back to per-process local memory when REDIS_URL is
# unset (tests, or a bare `manage.py runserver` without the compose stack);
# LocMem has no cross-process lock, so single-flight degrades to per-process
# there — fine for a single worker. IGNORE_EXCEPTIONS keeps the API serving
# straight from Postgres if Redis is down, so the cache is a speedup, never a
# hard dependency.
REDIS_URL = os.getenv('REDIS_URL')
if REDIS_URL:
    CACHES = {
        'default': {
            'BACKEND': 'django_redis.cache.RedisCache',
            'LOCATION': REDIS_URL,
            'OPTIONS': {
                'CLIENT_CLASS': 'django_redis.client.DefaultClient',
                'IGNORE_EXCEPTIONS': True,
            },
        }
    }
    DJANGO_REDIS_LOG_IGNORED_EXCEPTIONS = True
else:
    CACHES = {
        'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'},
    }

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

# Static files
STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Django REST Framework
REST_FRAMEWORK = {
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_RENDERER_CLASSES': [
        'rest_framework.renderers.JSONRenderer',
    ],
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.SessionAuthentication',
    ],
    # Per-visitor API cap. Share-link visitors all authenticate as one
    # demo_viewer user, so a user-keyed throttle would lump them together;
    # SessionOrIPRateThrottle keys on the session/IP instead. Login and
    # share-token endpoints get stricter IP-keyed throttles applied per-view.
    'DEFAULT_THROTTLE_CLASSES': [
        'api.throttles.SessionOrIPRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        'session': '120/min',
        'login': '10/min',
        'share_auth': '20/min',
    },
}

# CORS - allow frontend dev server
CORS_ALLOWED_ORIGINS = os.getenv(
    'CORS_ALLOWED_ORIGINS',
    'http://localhost:5173,http://localhost:5174,http://localhost:3000,http://127.0.0.1:5173,http://127.0.0.1:5174'
).split(',')
CORS_ALLOW_ALL_ORIGINS = DEBUG  # Allow all in dev
CORS_ALLOW_CREDENTIALS = True  # Allow cookies for session auth

# Session settings for cross-origin auth
SESSION_COOKIE_SAMESITE = 'Lax'
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_SAMESITE = 'Lax'
CSRF_COOKIE_HTTPONLY = False  # Allow JS to read the CSRF token
CSRF_TRUSTED_ORIGINS = os.getenv(
    'CSRF_TRUSTED_ORIGINS',
    'http://localhost:5173,http://localhost:5174,http://localhost:3000,http://127.0.0.1:5173,http://127.0.0.1:5174'
).split(',')

# In production, TLS is terminated at Caddy and Django is reached over http on
# the internal network. Trust the proxy's scheme header and mark cookies Secure
# so they aren't sent over plain http. (Caddy already does the http->https
# redirect and can set HSTS, so those aren't duplicated here.) Left off in DEBUG
# so local http dev keeps working.
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

# ---- Authentication backends / enterprise SSO (python-social-auth) -------
# Shipped default: plain Django auth (username/password + the share-link flow).
# ModelBackend is the only backend, so nothing changes unless a deployer opts
# in. Setting SSO_ENABLED=true adds a single corporate identity provider —
# Okta, Microsoft Entra, or Google Workspace — selected by dotted path
# (NetBox-style), as an *additional* login path. ModelBackend stays last so
# admin/superuser and share-link login keep working (an IdP outage can't lock
# you out of /admin). social_django is only installed when enabled, so a
# disabled deployment gets no new tables. Real tenant/client values live in the
# gitignored .env — never commit them. Full setup: docs/sso.md.
# Baseline access: newly-created users (SSO or local) are auto-added to this
# Django group, which grants read of everything via the standard `view_scanner`
# permission. To disable the read-all baseline, remove `view_scanner` from the
# group in the admin (auditable, revocable) — or set this empty to stop
# auto-adding new users. Writes still require an rw Access grant or staff; share
# links stay scoped. Applies with or without SSO. See core/signals.py.
DEFAULT_USER_GROUP = os.getenv('DEFAULT_USER_GROUP', 'Viewers')

import importlib

SSO_ENABLED = os.getenv('SSO_ENABLED', 'false').lower() == 'true'

AUTHENTICATION_BACKENDS = ['django.contrib.auth.backends.ModelBackend']

if SSO_ENABLED:
    INSTALLED_APPS += ['social_django']

    # Backend selected by dotted path (like NetBox's REMOTE_AUTH_BACKEND), e.g.
    #   social_core.backends.azuread_tenant.AzureADV2TenantOAuth2   (Entra, v2)
    #   social_core.backends.okta_openidconnect.OktaOpenIdConnect   (Okta)
    #   social_core.backends.google.GoogleOAuth2                    (Google)
    SSO_BACKEND = os.getenv('SSO_BACKEND', '')
    AUTHENTICATION_BACKENDS = [SSO_BACKEND, 'django.contrib.auth.backends.ModelBackend']

    # Resolve the backend's URL name (used in /oauth/login/<name>/ and by the
    # login button). Read from the backend class's `name` attribute.
    _mod, _cls = SSO_BACKEND.rsplit('.', 1)
    SSO_BACKEND_NAME = getattr(importlib.import_module(_mod), _cls).name

    # Import every SOCIAL_AUTH_* var straight from the environment (the same way
    # NetBox imports them from configuration.py). Deployers set the provider's
    # own SOCIAL_AUTH_<BACKEND>_KEY/SECRET/... in .env — see docs/sso.md.
    for _k, _v in os.environ.items():
        if _k.startswith('SOCIAL_AUTH_'):
            globals()[_k] = _v

    SOCIAL_AUTH_JSONFIELD_ENABLED = True  # JSONB extra_data on Postgres
    # TLS terminates at Caddy; build callback URLs as https in production.
    if not DEBUG:
        SOCIAL_AUTH_REDIRECT_IS_HTTPS = True

    # Where the provider returns the browser after login/logout.
    LOGIN_REDIRECT_URL = os.getenv('SSO_LOGIN_REDIRECT_URL', '/')
    LOGOUT_REDIRECT_URL = os.getenv('SSO_LOGOUT_REDIRECT_URL', '/')

    # Auth pipeline: psa default, but keep `auth_allowed` (domain gate via the
    # backend's WHITELISTED_DOMAINS) and add our step that puts new users in the
    # local default groups. No IdP group sync — authorization is the app's
    # Access model.
    SOCIAL_AUTH_PIPELINE = (
        'social_core.pipeline.social_auth.social_details',
        'social_core.pipeline.social_auth.social_uid',
        'social_core.pipeline.social_auth.auth_allowed',
        'social_core.pipeline.social_auth.social_user',
        'social_core.pipeline.user.get_username',
        'social_core.pipeline.user.create_user',
        'social_core.pipeline.social_auth.associate_user',
        'api.auth.pipeline.assign_default_groups',
        'social_core.pipeline.social_auth.load_extra_data',
        'social_core.pipeline.user.user_details',
    )

    # New SSO users are added to these LOCAL Django groups on first login for
    # baseline access (managed in the app, not synced from the IdP). The groups'
    # access comes from Access grants assigned to them.
    SSO_DEFAULT_GROUPS = [
        g.strip() for g in os.getenv('SSO_DEFAULT_GROUPS', '').split(',') if g.strip()
    ]

    # Login-button presentation (SPA + admin). SSO_PROVIDER_BRAND=microsoft
    # renders the branded "Sign in with Microsoft" button; any other value = a
    # neutral button showing SSO_BUTTON_LABEL. One setting themes both surfaces.
    SSO_PROVIDER_BRAND = os.getenv('SSO_PROVIDER_BRAND', 'generic')
    _default_sso_label = (
        'Sign in with Microsoft' if SSO_PROVIDER_BRAND == 'microsoft'
        else 'Sign in with SSO'
    )
    SSO_BUTTON_LABEL = os.getenv('SSO_BUTTON_LABEL', _default_sso_label)

# MQTT settings
MQTT_BROKER_HOST = os.getenv('MQTT_BROKER_HOST', 'localhost')
MQTT_BROKER_PORT = int(os.getenv('MQTT_BROKER_PORT', 1883))
MQTT_CLIENT_ID = os.getenv('MQTT_CLIENT_ID', 'spectrum-server')
MQTT_TOPIC_PREFIX = os.getenv('MQTT_TOPIC_PREFIX', 'spectrum')
# MQTT bridge service credentials (subscribe-only internal service)
MQTT_BRIDGE_USERNAME = os.getenv('MQTT_BRIDGE_USERNAME', '')
MQTT_BRIDGE_PASSWORD = os.getenv('MQTT_BRIDGE_PASSWORD', '')
# Read-only $SYS metrics user (optional — dynsec provisions it only when the
# password is set; must match observability/.env's MQTT_MONITOR_PASSWORD).
MQTT_MONITOR_USERNAME = os.getenv('MQTT_MONITOR_USERNAME', 'monitor')
MQTT_MONITOR_PASSWORD = os.getenv('MQTT_MONITOR_PASSWORD', '')
# MQTT Dynamic Security admin credentials (for provisioning clients/roles)
MQTT_DYNSEC_USERNAME = os.getenv('MOSQUITTO_DYNSEC_USERNAME', 'admin')
MQTT_DYNSEC_PASSWORD = os.getenv('MOSQUITTO_DYNSEC_PASSWORD', '')

# Logging
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
    'loggers': {
        'api': {
            'handlers': ['console'],
            'level': 'DEBUG',
            'propagate': False,
        },
    },
}
