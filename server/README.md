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
                    ┌────────────────────────┐
                    │     MQTT Broker        │
                    │     (Mosquitto)        │
                    └────────────┬───────────┘
                                 │
                                 ▼
┌────────────────────────────────────────────────────────────────────┐
│                        Spectrum Server                             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────────┐  │
│  │ MQTT Bridge  │──│   Django     │──│   Django Channels        │  │
│  │              │  │   REST API   │  │   (WebSocket)            │  │
│  └──────────────┘  └──────────────┘  └──────────────────────────┘  │
│         │                  │                      │                │
│         └──────────────────┼──────────────────────┘                │
│                            ▼                                       │
│                   ┌──────────────┐                                 │
│                   │   Database   │                                 │
│                   │   (SQLite/   │                                 │
│                   │   PostgreSQL)│                                 │
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

### Django Channels (`realtime/`)
- WebSocket endpoint at `/ws/scans/`
- Subscribe/unsubscribe to individual scanner streams
- Real-time scan data forwarding

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
- MQTT Broker (Mosquitto)
- Redis (for Django Channels)

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

### Docker Deployment

```bash
# From project root
docker-compose up -d
```

Services:
- `server` - Django + Daphne (port 8000)
- `mosquitto` - MQTT broker (port 1883)
- `redis` - Channel layer backend
- `frontend` - Vue dev server (port 5173)

### Production Deployment

1. **Database**: Switch from SQLite to PostgreSQL
   ```python
   # config/settings.py
   DATABASES = {
       'default': {
           'ENGINE': 'django.db.backends.postgresql',
           'NAME': 'spectrum',
           'USER': 'spectrum',
           'PASSWORD': 'your-password',
           'HOST': 'localhost',
           'PORT': '5432',
       }
   }
   ```

2. **Static Files**: Build and collect
   ```bash
   cd frontend && npm run build
   python manage.py collectstatic
   ```

3. **ASGI Server**: Use Daphne or Uvicorn
   ```bash
   daphne -b 0.0.0.0 -p 8000 config.asgi:application
   ```

4. **Process Manager**: Use systemd or supervisor
   ```ini
   # /etc/supervisor/conf.d/spectrum.conf
   [program:spectrum-server]
   command=/path/to/venv/bin/daphne -b 0.0.0.0 -p 8000 config.asgi:application
   directory=/path/to/server
   autostart=true
   autorestart=true

   [program:spectrum-mqtt]
   command=/path/to/venv/bin/python manage.py mqtt_bridge
   directory=/path/to/server
   autostart=true
   autorestart=true
   ```

5. **Reverse Proxy**: Nginx configuration
   ```nginx
   upstream spectrum {
       server 127.0.0.1:8000;
   }

   server {
       listen 80;
       server_name spectrum.example.com;

       location / {
           proxy_pass http://spectrum;
           proxy_http_version 1.1;
           proxy_set_header Upgrade $http_upgrade;
           proxy_set_header Connection "upgrade";
           proxy_set_header Host $host;
           proxy_set_header X-Real-IP $remote_addr;
       }
   }
   ```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `DEBUG` | Django debug mode | `True` |
| `SECRET_KEY` | Django secret key | (generated) |
| `ALLOWED_HOSTS` | Comma-separated hosts | `localhost,127.0.0.1` |
| `DATABASE_URL` | Database connection URL | SQLite |
| `REDIS_URL` | Redis connection URL | `redis://localhost:6379` |
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
