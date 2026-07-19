# Observability

A single **Telegraf** worker that ships **host + docker + mosquitto `$SYS`**
metrics to **VictoriaMetrics** (InfluxDB line protocol), plus a sample Grafana
dashboard. Reuses the standard Telegraf → VictoriaMetrics → Grafana pipeline, so
it drops into any deployment — nothing here is specific to one host (real
endpoints/secrets live in the gitignored `.env`).

```
this host (server stack)                      your metrics box
┌───────────────────────────┐   HTTPS/write   ┌──────────────────────────┐
│ telegraf                  │────────────────▶│ VictoriaMetrics ─▶ Grafana│
│  • host cpu/mem/disk/net  │                 └──────────────────────────┘
│  • docker (per-container) │
│  • mosquitto $SYS (viewers,│
│    egress, msg rate)      │
└───────────────────────────┘
```

## 1. Configure

```bash
cd observability
cp .env.example .env
# edit .env:
#   VM_URL / VM_USERNAME / VM_PASSWORD   → your VictoriaMetrics write endpoint
#   MQTT_MONITOR_USERNAME / _PASSWORD    → the broker monitor user (step 2)
#   TELEGRAF_HOSTNAME                    → a label for this deployment
#   DOCKER_GID                           → getent group docker | cut -d: -f3
```

`MQTT_URL` defaults to `tcp://host.docker.internal:1883` — the broker's published
port on the same host. (For an encrypted broker, use `wss://…/mqtt` + monitor
creds.)

## 2. Provision the broker monitor user

The broker runs `allow_anonymous=false`, so Telegraf needs a credential — and it's
**provisioned automatically** by the server's dynsec sync (`realtime/dynsec.py`
`ensure_monitor_client`). Set the SAME `MQTT_MONITOR_PASSWORD` in the **server**
stack's `.env` (matching this worker's `.env`), then apply it:

```bash
# in the server stack dir, with MQTT_MONITOR_PASSWORD set in server/.env
docker compose -f docker-compose.prod.yml up -d server mqtt-bridge   # pick up the new env
docker compose -f docker-compose.prod.yml exec server uv run python manage.py dynsec_sync
```

That creates a `monitor` role/client with subscribe **and** receive on `$SYS/#`
only — no `spectrum/#` access, no publish. It's a no-op unless
`MQTT_MONITOR_PASSWORD` is set, so deployments without metrics are unaffected. (A
valid credential is all that's needed to *connect*; those two ACLs are what make
the stats actually flow.)

## 3. Run

```bash
docker compose -f observability/docker-compose.yml up -d
docker compose -f observability/docker-compose.yml logs -f telegraf   # confirm writes
```

## 4. Grafana dashboard

Import `grafana/spectrum-demo.json` into Grafana (or drop it in your Grafana
provisioning dir). It has a `datasource` variable — pick your VictoriaMetrics
datasource. Panels: concurrent viewers (`$SYS` connected − infra clients),
egress, message rate, host CPU/mem/disk, per-container memory, and Caddy HTTP
(req/s, errors/s, p99 latency).

## Notes

- **Viewer count** = `mqtt_consumer_value{topic="$SYS/broker/clients/connected"}`
  minus your infra clients (scanners + the server bridge + this monitor). The
  dashboard subtracts a constant you set in its `infra_clients` variable.
- **Multiple deployments** stay separate via the `host` tag (`TELEGRAF_HOSTNAME`).
- **Caddy metric names:** the `caddy_http_*` panels assume Telegraf's
  `metric_version = 2` naming. If those panels are empty, browse the metrics in
  Grafana / vmui — the influx→VM path can add a `_value` suffix or similar; adjust
  the panel queries to what's actually stored.
- **Web analytics** are handled separately by the frontend/Django `ANALYTICS_EMBED`
  (Umami/Plausible/etc.) — see `server/.env.example`. This worker is
  infrastructure metrics only.
