#!/bin/sh
set -e

# Run migrations
uv run python manage.py migrate --noinput

# Collect static files
uv run python manage.py collectstatic --noinput

# Start gunicorn
# Workers x threads sets the concurrent-request capacity. The read path is
# I/O-bound (Postgres + Redis waits) and now cached, so threads give cheap
# concurrency for the demo's fan-out; keep worker count modest since each holds
# large scan arrays in memory. Tune per instance via env.
# max-requests: recycle workers periodically to prevent memory leaks.
exec uv run gunicorn \
    --bind 0.0.0.0:8000 \
    --workers ${GUNICORN_WORKERS:-4} \
    --threads ${GUNICORN_THREADS:-4} \
    --max-requests 500 \
    --max-requests-jitter 50 \
    config.wsgi:application
