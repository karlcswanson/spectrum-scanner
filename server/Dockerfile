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

# Dev: use runserver for auto-reload
CMD ["uv", "run", "python", "manage.py", "runserver", "0.0.0.0:8000"]
