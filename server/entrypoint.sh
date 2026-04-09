#!/bin/sh
set -e

# Run migrations
uv run python manage.py migrate --noinput

# Collect static files
uv run python manage.py collectstatic --noinput

# Start gunicorn
# Workers: 2 is sufficient for this workload (scan data is large per-request)
# max-requests: recycle workers periodically to prevent memory leaks
exec uv run gunicorn \
    --bind 0.0.0.0:8000 \
    --workers ${GUNICORN_WORKERS:-2} \
    --threads 2 \
    --max-requests 500 \
    --max-requests-jitter 50 \
    config.wsgi:application
