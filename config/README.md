# Production Deployment

## Quick Start

1. Copy the environment file and configure:
   ```bash
   cp .env.example .env
   # Edit .env with your settings
   ```

2. Build and start services:
   ```bash
   docker compose -f docker-compose.prod.yml up -d --build
   ```

3. Access the application:
   - Local testing: http://localhost
   - With domain: https://your-domain.com (automatic HTTPS via Caddy)

## Configuration

### Required Environment Variables

| Variable | Description |
|----------|-------------|
| `DOMAIN` | Your domain name (e.g., `spectrum.example.com`) or `localhost` for testing |
| `DJANGO_SECRET_KEY` | A secure random string for Django |
| `MQTT_BRIDGE_PASSWORD` | Password for the internal MQTT bridge service |

### Optional Variables

See `.env.example` for all available configuration options.

## Services

| Service | Description | Port |
|---------|-------------|------|
| caddy | Reverse proxy + HTTPS | 80, 443 |
| server | Django REST API | internal |
| mosquitto | MQTT broker | 1883 (external for scanners) |
| mqtt-bridge | Saves MQTT data to database | internal |
| frontend | Vue.js static files | internal |

## Architecture

```
                    ┌─────────────────┐
  Scanners ─────────│   Mosquitto     │
     (MQTT 1883)    │   (MQTT Broker) │
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │   mqtt-bridge   │
                    │ (saves to DB)   │
                    └────────┬────────┘
                             │
  Browsers ─────────┐        ▼
     (HTTPS 443)    │  ┌───────────┐
                    ├──│   Caddy   │
                    │  │  (proxy)  │
                    │  └─────┬─────┘
                    │        │
              ┌─────▼──┐  ┌──▼───┐
              │Frontend│  │Django│
              │ (Vue)  │  │(API) │
              └────────┘  └──────┘
```

## SSL/HTTPS

Caddy automatically obtains and renews SSL certificates from Let's Encrypt when:
1. `DOMAIN` is set to a real domain (not `localhost`)
2. Ports 80 and 443 are accessible from the internet
3. DNS is configured to point to your server

For local testing, Caddy serves HTTP on port 80.

## Database

By default, SQLite is used (stored in `server_data` volume). For production with higher load, configure PostgreSQL:

```env
DB_ENGINE=django.db.backends.postgresql
DB_NAME=spectrum
DB_USER=spectrum
DB_PASSWORD=your-password
DB_HOST=postgres
DB_PORT=5432
```

Add PostgreSQL to `docker-compose.prod.yml` if needed.

## Logs

```bash
# All services
docker compose -f docker-compose.prod.yml logs -f

# Specific service
docker compose -f docker-compose.prod.yml logs -f server
```

## Updating

```bash
docker compose -f docker-compose.prod.yml down
git pull
docker compose -f docker-compose.prod.yml up -d --build
```
