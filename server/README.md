# Spectrum Server

Central server for aggregating and visualizing spectrum scan data from multiple ADALM-Pluto scanners.

## Components

### MQTT Bridge (`realtime/mqtt_bridge.py`)
- Subscribes to scanner topics from MQTT broker
- Forwards real-time scan data to WebSocket clients
- Stores scans to database (rate-limited to 1/minute per band)
- Handles scanner config and status messages

### Django REST API (`api/`)
- `GET /api/scanners/` - List all scanners
- `GET /api/scanners/{id}/` - Scanner details
- `GET /api/scanners/{id}/history/` - Historical scans (24h max)
- `GET /api/scanners/{id}/timeline/` - Scan timestamps for scrubber
- `GET /api/scans/at_time/` - Get scan closest to timestamp

### Database Models (`core/models.py`)
- `Scanner` - Scanner devices and their status
- `Band` - Frequency bands per scanner
- `Scan` - Stored spectrum scans with power data
- `ScanSummary` - Rolled-up summaries (peak/average) at configurable resolutions
- `ScannerGroup` - Logical groupings of scanners
- `Access` - User/token permission grants for scanners and groups
- `SiteSettings` - Global key-value configuration (e.g. retention policy)

## MQTT Topics

Scanners publish to:
```
spectrum/scanners/{scanner_id}/scan    - Scan data (QoS 0)
spectrum/scanners/{scanner_id}/status  - Online/scanning state (retained)
spectrum/scanners/{scanner_id}/config  - Scanner configuration (retained)
```

## Deployment

### Prerequisites
- Python 3.14+ and [uv](https://docs.astral.sh/uv/)
- Docker and Docker Compose (recommended)

### Development Setup (Local)

```bash
cd server

# Install dependencies
uv sync

# Run migrations
uv run python manage.py migrate

# Start the server
uv run python manage.py runserver
```

In a separate terminal:
```bash
# Start the MQTT bridge
uv run python manage.py mqtt_bridge
```

### Docker Development

```bash
cd server
docker compose up -d

# Create admin user (first run)
docker compose exec server uv run python manage.py createsuperuser
```

Services:
- `postgres` - PostgreSQL 16 (port 5432)
- `server` - Django dev server (port 8000)
- `mosquitto` - MQTT broker (port 1883, WebSocket 9001)
- `mqtt-bridge` - Saves MQTT data to database, runs rollup
- `frontend` - Vue dev server (port 5174)

### Docker Production Deployment

The production setup uses Caddy for reverse proxy with automatic HTTPS.

#### Quick Start

```bash
# 1. Copy and configure environment
cp .env.example .env

# 2. Edit .env with your settings:
#    - DOMAIN: your domain name (or localhost for testing)
#    - DJANGO_SECRET_KEY: generate a secure random string
#    - MQTT_BRIDGE_PASSWORD: password for internal MQTT service

# 3. Build and start
docker compose -f docker-compose.prod.yml up -d --build

# 4. Create admin user (first run only)
docker compose -f docker-compose.prod.yml exec server python manage.py createsuperuser

# 5. Check logs
docker compose -f docker-compose.prod.yml logs -f
```

#### Deploy from source vs. pull prebuilt images

Every custom service in `docker-compose.prod.yml` declares **both** `build:` and
`image:`, so you can deploy either way — the `image:` name is just the tag the
local build gets; it does not force a registry pull.

**From source (default; no CI, no registry auth needed):** check out the branch
on the server and build there.

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

Use `--build` (or `pull` below) explicitly — a bare `up -d` uses whatever image
is already local and only builds if none exists. To populate `/api/version` on a
source build, pass the git refs as build args:

```bash
GIT_SHA=$(git rev-parse --short HEAD) GIT_REF=$(git rev-parse --abbrev-ref HEAD) \
  docker compose -f docker-compose.prod.yml up -d --build
```

**From prebuilt images (CI publishes to GHCR):** pull instead of build. Pick the
tag with `SERVER_TAG` / `FRONTEND_TAG` (default `latest`; CI also tags `main`,
`sha-<short>`, and semver on `v*` tags).

```bash
SERVER_TAG=main FRONTEND_TAG=main docker compose -f docker-compose.prod.yml pull
docker compose -f docker-compose.prod.yml up -d
```

#### First Run Setup

After starting the server, create an admin user and configure scanners:

1. **Create superuser** (see step 4 above)
2. **Access admin panel** at `https://your-domain/admin/`
3. **Add scanners** - create Scanner entries with:
   - UUID (auto-generated or custom)
   - Auth token (for MQTT authentication)
   - Enabled flag
4. **Configure scanner** - copy the UUID and token to the scanner's `config.yaml`:
   ```yaml
   mqtt:
     enabled: true
     broker: "tcp://your-domain:1883"
     id: "scanner-uuid-from-admin"
     token: "auth-token-from-admin"
   ```

#### Production Services

| Service | Description | Ports |
|---------|-------------|-------|
| `caddy` | Reverse proxy + auto HTTPS | 80, 443 |
| `server` | Django + Gunicorn (4 workers) | internal |
| `postgres` | PostgreSQL database | internal |
| `redis` | Read-cache (history/timeline) | internal |
| `mosquitto` | MQTT broker | 1883 (scanners) |
| `mqtt-bridge` | Saves scans to database | internal |
| `scheduler` | Retention rollup + cache pre-warm | internal |
| `frontend` | Vue static files | internal |

#### Environment Variables

Create a `.env` file in the server directory:

```env
# Required
DOMAIN=spectrum.example.com
DJANGO_SECRET_KEY=your-secure-random-key
MQTT_BRIDGE_PASSWORD=your-bridge-password

# Optional
DEBUG=false
# NOTE: Must include 'localhost' and 'server' for Mosquitto auth plugin
ALLOWED_HOSTS=spectrum.example.com,localhost,server

# Database
DB_NAME=spectrum
DB_USER=spectrum
DB_PASSWORD=db-password

# Redis read-cache + MQTT bridge identity (defaults shown; override if needed)
REDIS_URL=redis://redis:6379/0
MQTT_BRIDGE_USERNAME=spectrum-bridge

# Image tags for pull-based deploys (default: latest). See "Deploy from source
# vs. pull prebuilt images" above.
# SERVER_TAG=main
# FRONTEND_TAG=main
```

#### SSL/HTTPS

Caddy automatically obtains Let's Encrypt certificates when:
1. `DOMAIN` is set to a real domain (not `localhost`)
2. Ports 80 and 443 are accessible from the internet
3. DNS points to your server

For local testing, Caddy serves HTTP on port 80.

#### Managing the Deployment

```bash
# View logs
docker compose -f docker-compose.prod.yml logs -f server

# Restart a service
docker compose -f docker-compose.prod.yml restart server

# Update deployment
docker compose -f docker-compose.prod.yml down
git pull
docker compose -f docker-compose.prod.yml up -d --build

# Access Django shell
docker compose -f docker-compose.prod.yml exec server python manage.py shell

# Run migrations
docker compose -f docker-compose.prod.yml exec server python manage.py migrate
```

#### Data Persistence

Data is stored in Docker volumes:
- `postgres_data` - PostgreSQL database
- `mosquitto_data` - MQTT persistence
- `caddy_data` - SSL certificates

To backup:
```bash
docker compose -f docker-compose.prod.yml exec postgres \
  pg_dump -U spectrum spectrum > backup.sql
```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `DEBUG` | Django debug mode | `false` |
| `DJANGO_SECRET_KEY` | Django secret key | dev fallback |
| `ALLOWED_HOSTS` | Comma-separated hosts | `localhost,127.0.0.1,server` |
| `DB_NAME` | Database name | `spectrum` |
| `DB_USER` | Database user | `spectrum` |
| `DB_PASSWORD` | Database password | (required in prod) |
| `MQTT_BROKER_HOST` | MQTT broker hostname | `localhost` |
| `MQTT_BROKER_PORT` | MQTT broker port | `1883` |
| `MQTT_BRIDGE_USERNAME` | MQTT bridge service user | `spectrum-bridge` |
| `MQTT_BRIDGE_PASSWORD` | MQTT bridge service password | (required in prod) |

## Data Retention

The MQTT bridge automatically rolls up scan data on a Graphite/Whisper-style tiered schedule. The default retention policy is:

```
1s:24h, 1m:7d, 5m:30d, 1h:1y
```

This means: keep raw scans for 24 hours, then 1-minute summaries for 7 days, 5-minute summaries for 30 days, and 1-hour summaries for 1 year.

The retention policy can be overridden globally via **Site Settings** in the Django admin, or per-scanner in the scanner's **Data Retention** fieldset.

To run rollup manually:
```bash
# Dry run (show what would be rolled up/purged)
docker compose exec server uv run python manage.py rollup --dry-run

# Run rollup
docker compose exec server uv run python manage.py rollup
```

You can also trigger rollup from the Django admin under **Scan Summaries > Run Rollup**.
