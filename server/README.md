# Spectrum Server

Central server for aggregating and visualizing spectrum scan data from multiple ADALM-Pluto scanners.

## Architecture

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  Pluto Scanner  │     │  Pluto Scanner  │     │  Pluto Scanner  │
│   (Studio A)    │     │   (Main Stage)  │     │   (FOH)         │
└────────┬────────┘     └────────┬────────┘     └────────┬────────┘
         │                       │                       │
         │ MQTT                  │ MQTT                  │ MQTT
         │                       │                       │
         └───────────────────────┼───────────────────────┘
                                 │
                                 ▼
┌────────────────────────────────────────────────────────────────────┐
│                        Spectrum Server                             │
│                                                                    │
│  ┌──────────────┐                                                  │
│  │  Mosquitto   │◀─── Scanners connect here (port 1883)            │
│  │ MQTT Broker  │                                                  │
│  └──────┬───────┘                                                  │
│         │                                                          │
│         ▼                                                          │
│  ┌──────────────┐  ┌──────────────┐                                │
│  │ MQTT Bridge  │──│   Django     │                                │
│  │              │  │   REST API   │                                │
│  └──────────────┘  └──────────────┘                                │
│         │                  │                      │                │
│         └──────────────────┼──────────────────────┘                │
│                            ▼                                       │
│                   ┌──────────────┐                                 │
│                   │   Database   │                                 │
│                   └──────────────┘                                 │
└────────────────────────────────────────────────────────────────────┘
                                 │
                                 │ WebSocket
                                 ▼
                    ┌────────────────────────┐
                    │     Vue Frontend       │
                    │   (Browser Clients)    │
                    └────────────────────────┘
```

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
- `ScanAggregate` - Aggregated data (max hold, average)

## MQTT Topics

Scanners publish to:
```
spectrum/scanners/{scanner_id}/scan    - Scan data (QoS 0)
spectrum/scanners/{scanner_id}/status  - Online/scanning state (retained)
spectrum/scanners/{scanner_id}/config  - Scanner configuration (retained)
```

## Deployment

### Prerequisites
- Python 3.11+
- Docker and Docker Compose (recommended)
- Or: MQTT Broker (Mosquitto) for manual setup

### Development Setup

```bash
cd server

# Create virtual environment
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run migrations
python manage.py migrate

# Start the server (runs Django + MQTT bridge)
python manage.py runserver
```

In a separate terminal:
```bash
# Start the MQTT bridge
python manage.py mqtt_bridge
```

### Docker Development

```bash
cd server
docker compose up -d
```

Services:
- `server` - Django dev server (port 8000)
- `mosquitto` - MQTT broker (port 1883, WebSocket 9001)
- `mqtt-bridge` - Saves MQTT data to database
- `frontend` - Vue dev server (port 5173)

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
| `mosquitto` | MQTT broker | 1883 (scanners) |
| `mqtt-bridge` | Saves scans to database | internal |
| `frontend` | Vue static files | internal |

#### Production Architecture

```
Scanners ──────► Mosquitto:1883 ──────► mqtt-bridge ──► Database
                      │
                      │ WebSocket
                      ▼
Browsers ──────► Caddy:443 ─────┬────► /mqtt (Mosquitto:9001)
   (HTTPS)                      ├────► /api/* (Django:8000)
                                └────► /* (Vue static files)
```

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

# Database (SQLite default, or PostgreSQL)
DB_ENGINE=django.db.backends.sqlite3
DB_NAME=/app/data/db.sqlite3

# For PostgreSQL:
# DB_ENGINE=django.db.backends.postgresql
# DB_NAME=spectrum
# DB_USER=spectrum
# DB_PASSWORD=db-password
# DB_HOST=postgres
# DB_PORT=5432
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
- `server_data` - SQLite database
- `mosquitto_data` - MQTT persistence
- `caddy_data` - SSL certificates

To backup:
```bash
docker compose -f docker-compose.prod.yml exec server \
  cp /app/data/db.sqlite3 /app/data/db.sqlite3.backup
```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `DEBUG` | Django debug mode | `True` |
| `SECRET_KEY` | Django secret key | (generated) |
| `ALLOWED_HOSTS` | Comma-separated hosts | `localhost,127.0.0.1` |
| `DATABASE_URL` | Database connection URL | SQLite |
| `MQTT_BROKER_HOST` | MQTT broker hostname | `localhost` |
| `MQTT_BROKER_PORT` | MQTT broker port | `1883` |

## Data Retention

By default, the MQTT bridge stores one scan per minute per band. To manage database size:

```python
# Clean up scans older than 7 days
python manage.py shell
>>> from django.utils import timezone
>>> from datetime import timedelta
>>> from core.models import Scan
>>> cutoff = timezone.now() - timedelta(days=7)
>>> Scan.objects.filter(timestamp__lt=cutoff).delete()
```

Consider setting up a cron job for automatic cleanup.
