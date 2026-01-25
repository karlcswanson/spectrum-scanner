# Configuration Examples

This directory contains example configuration files and production deployment configs.

## Files

| File | Description |
|------|-------------|
| `owon-example.yaml` | Example config for OWON spectrum analyzer |
| `docker-compose.prod.yml` | Production Docker Compose |
| `Caddyfile` | Caddy reverse proxy config |
| `mosquitto.conf` | Mosquitto MQTT broker config |
| `.env.example` | Environment variables template |

## Production Deployment

See [server/README.md](../server/README.md) for full deployment instructions.

Quick start:
```bash
cp .env.example .env
# Edit .env with your settings
docker compose -f docker-compose.prod.yml up -d --build
```
