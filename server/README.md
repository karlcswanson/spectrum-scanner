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
- `redis` - Response cache + single-flight locks for the read API
- `scheduler` - Per-scanner rollup + periodic dynsec sync (APScheduler)
- `frontend` - Vue dev server (port 5174)

### Docker Production Deployment

The production setup uses Caddy for reverse proxy, with HTTPS via Let's Encrypt
(public) or a self-signed internal CA (LAN) — see [SSL/HTTPS](#sslhttps).

> **Starting from a bare machine?** See [`../deploy/`](../deploy/) for VM
> provisioning (cloud-init, Proxmox) and **`deploy/bootstrap.sh`**, which
> automates the `.env` + secrets + `up` steps below in one command.

#### Quick Start

```bash
# 1. Copy and configure environment
cp .env.example .env

# 2. Edit .env — one file drives both modes (see the comments in .env.example):
#    - PUBLIC: DOMAIN=your-domain.com, SITE_TLS= (empty -> Let's Encrypt)
#    - LAN:    DOMAIN=<host-ip>, SITE_TLS=tls internal, ALLOWED_HOSTS=*
#    - secrets: DJANGO_SECRET_KEY, DB_PASSWORD, MOSQUITTO_DYNSEC_PASSWORD,
#      MQTT_BRIDGE_PASSWORD   (or just run ../deploy/bootstrap.sh to fill these)

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

`.env.example` is the source of truth (copy it to `.env`); it documents both
deployment modes inline. The essentials:

```env
# Network / TLS — set for ONE mode (see .env.example for the full block)
DOMAIN=spectrum.example.com        # or the host IP for LAN
SITE_TLS=                          # empty = Let's Encrypt; "tls internal" = LAN self-signed
ALLOWED_HOSTS=spectrum.example.com,localhost,127.0.0.1,server   # or * on a trusted LAN
CSRF_TRUSTED_ORIGINS=https://spectrum.example.com
CORS_ALLOWED_ORIGINS=https://spectrum.example.com

# Required secrets (compose refuses to start without these)
DJANGO_SECRET_KEY=...              # python3 -c 'import secrets; print(secrets.token_urlsafe(64))'
DB_PASSWORD=...
MOSQUITTO_DYNSEC_PASSWORD=...      # broker Dynamic Security admin
MQTT_BRIDGE_PASSWORD=...           # bridge service

# Database (defaults shown)
DB_NAME=spectrum
DB_USER=spectrum

# Optional: image tags for pull-based deploys (default: latest)
# SERVER_TAG=main
# FRONTEND_TAG=main
```

#### SSL/HTTPS

TLS mode is env-driven via `SITE_TLS`, so one Caddyfile serves both:

- **Public** (`SITE_TLS=` empty): Caddy auto-obtains a Let's Encrypt cert when
  `DOMAIN` is a real domain, ports 80/443 are internet-reachable, and DNS points
  at the server.
- **LAN / offline** (`SITE_TLS=tls internal`): Caddy issues a self-signed cert
  from its own internal CA — no internet needed. Access by the host IP works
  (Caddy's `default_sni` handles the no-SNI-on-a-bare-IP case, which otherwise
  aborts the handshake with `ERR_SSL_PROTOCOL_ERROR`); browsers still warn on the
  self-signed cert, so trust Caddy's root (in the `caddy_data` volume at
  `/data/caddy/pki/authorities/local/root.crt`) or click through.

See `.env.example` for the full per-mode variable set, or use
`../deploy/bootstrap.sh` to configure it automatically.

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
| `DOMAIN` | Site address (domain or host IP) | `localhost` |
| `SITE_TLS` | Empty = Let's Encrypt; `tls internal` = self-signed LAN CA | (empty) |
| `DEBUG` | Django debug mode | `false` |
| `DJANGO_SECRET_KEY` | Django secret key | dev fallback |
| `ALLOWED_HOSTS` | Comma-separated hosts (or `*` on a trusted LAN) | `localhost,127.0.0.1,server` |
| `CSRF_TRUSTED_ORIGINS` | Trusted origins (scheme+host) for unsafe requests | (dev origins) |
| `CORS_ALLOWED_ORIGINS` | Allowed CORS origins | (dev origins) |
| `DB_NAME` / `DB_USER` | Database name / user | `spectrum` / `spectrum` |
| `DB_PASSWORD` | Database password | (required in prod) |
| `MOSQUITTO_DYNSEC_PASSWORD` | Broker Dynamic Security admin password | (required in prod) |
| `MQTT_BRIDGE_USERNAME` | MQTT bridge service user | `spectrum-bridge` |
| `MQTT_BRIDGE_PASSWORD` | MQTT bridge service password | (required in prod) |

The broker host/port aren't configurable here — they're fixed by the compose
topology (`mosquitto:1883` internal, `:9001` WebSocket via Caddy).

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
