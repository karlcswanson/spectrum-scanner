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

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
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

# MQTT settings
MQTT_BROKER_HOST = os.getenv('MQTT_BROKER_HOST', 'localhost')
MQTT_BROKER_PORT = int(os.getenv('MQTT_BROKER_PORT', 1883))
MQTT_CLIENT_ID = os.getenv('MQTT_CLIENT_ID', 'spectrum-server')
MQTT_TOPIC_PREFIX = os.getenv('MQTT_TOPIC_PREFIX', 'spectrum')
# MQTT bridge service credentials (subscribe-only internal service)
MQTT_BRIDGE_USERNAME = os.getenv('MQTT_BRIDGE_USERNAME', '')
MQTT_BRIDGE_PASSWORD = os.getenv('MQTT_BRIDGE_PASSWORD', '')
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
