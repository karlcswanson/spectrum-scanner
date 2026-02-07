FROM python:3.14-slim

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV UV_PROJECT_ENVIRONMENT=/usr/local

WORKDIR /app

# Install dependencies
COPY pyproject.toml uv.lock* ./
RUN uv sync --frozen --no-dev --no-install-project

# Copy application
COPY . .

# Create data directory
RUN mkdir -p /app/data

EXPOSE 8000

# Workers auto-scale: (2 * CPU cores) + 1
CMD ["sh", "-c", "uv run gunicorn --bind 0.0.0.0:8000 --workers $(( 2 * $(nproc) + 1 )) config.wsgi:application"]
