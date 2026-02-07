#!/bin/sh
set -e

# Run migrations
uv run python manage.py migrate --noinput

# Collect static files
uv run python manage.py collectstatic --noinput

# Start gunicorn with auto-scaling workers: (2 * CPU cores) + 1
exec uv run gunicorn \
    --bind 0.0.0.0:8000 \
    --workers $(( 2 * $(nproc) + 1 )) \
    --threads 2 \
    config.wsgi:application
