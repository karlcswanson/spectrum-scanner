# MQTT Architecture

## Overview

The system uses MQTT for real-time communication between scanners, the server, and frontend clients.

```
┌──────────────┐       ┌──────────────┐       ┌──────────────┐
│   Scanner    │       │   Scanner    │       │   Scanner    │
│  (Pluto/SCPI)│       │  (Pluto/SCPI)│       │  (Pluto/SCPI)│
└──────┬───────┘       └──────┬───────┘       └──────┬───────┘
       │ publish              │ publish              │ publish
       │ scan/status/config   │                      │
       ▼                      ▼                      ▼
┌─────────────────────────────────────────────────────────────┐
│                     Mosquitto Broker                         │
│                                                              │
│  Port 1883: MQTT (scanners, bridge)                         │
│  Port 9001: WebSocket (browser clients)                     │
│                                                              │
│  Auth: mosquitto-go-auth → Django /api/auth/mqtt/           │
└───────────────────────────┬─────────────────────────────────┘
                            │
        ┌───────────────────┼───────────────────┐
        │ subscribe         │ subscribe         │ subscribe
        ▼                   ▼                   ▼
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│ MQTT Bridge  │    │   Frontend   │    │   Frontend   │
│   (Django)   │    │  (Browser)   │    │  (Browser)   │
│              │    │              │    │              │
│ Stores scans │    │ Displays     │    │ Displays     │
│ to database  │    │ live data    │    │ live data    │
│              │    │              │    │              │
│ Publishes    │    │              │    │              │
│ timeline     │    │              │    │              │
│ updates      │    │              │    │              │
└──────────────┘    └──────────────┘    └──────────────┘
```

## Topic Hierarchy

```
spectrum/
├── scanners/
│   └── {scanner-uuid}/
│       ├── scan              # Live scan data (from scanner)
│       ├── status            # Scanner status (from scanner)
│       ├── config            # Scanner configuration (from scanner, retained)
│       └── timeline          # New DB record notification (from bridge)
│
├── commands/
│   └── {scanner-uuid}/
│       ├── start             # Start scanning command
│       ├── stop              # Stop scanning command
│       ├── bands             # Update band enabled states
│       └── gain              # Update gain settings
│
└── server/
    └── announce              # Server presence/heartbeat (future)
```

## Message Formats

### spectrum/scanners/{uuid}/scan

Live scan data, published by scanner after each band sweep completes.

```json
{
  "timestamp": "2025-12-09T19:30:00Z",
  "band": "UHF",
  "hz_lo": 470000000,
  "hz_hi": 608000000,
  "step": 12207.03125,
  "power": [-85.2, -82.1, -90.5, ...]
}
```

| Field | Type | Description |
|-------|------|-------------|
| timestamp | string | ISO 8601 timestamp |
| band | string | Band name (matches config) |
| hz_lo | int | Start frequency in Hz |
| hz_hi | int | Stop frequency in Hz |
| step | float | Frequency step in Hz |
| power | float[] | Power values in dBm |

**QoS:** 0 (at most once) - scans are frequent, losing one is acceptable
**Retain:** false

### spectrum/scanners/{uuid}/status

Scanner operational status, published by scanner on state changes.

```json
{
  "online": true,
  "scanning": true,
  "current_band": "UHF"
}
```

**QoS:** 1 (at least once)
**Retain:** true - new subscribers see current status

### spectrum/scanners/{uuid}/config

Full scanner configuration, published by scanner on connect and config changes.

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "name": "Studio A Scanner",
  "type": "pluto",
  "location": "Studio A",
  "description": "ADALM-Pluto Scanner",
  "bands": [
    {
      "name": "UHF",
      "start_hz": 470000000,
      "stop_hz": 608000000,
      "enabled": true
    },
    {
      "name": "WiFi 2.4",
      "start_hz": 2400000000,
      "stop_hz": 2500000000,
      "enabled": false
    }
  ],
  "settings": {
    "dwell_time_ms": 200,
    "rx_gain": 40,
    "rx_gain_mode": "manual",
    "mode": "Average"
  }
}
```

**QoS:** 1
**Retain:** true

### spectrum/scanners/{uuid}/timeline

Notification that a scan was stored in the database, published by MQTT bridge.
Includes full scan data so frontend can add to cache without API call.

```json
{
  "id": 12345,
  "timestamp": "2025-12-09T19:30:00Z",
  "band__name": "UHF",
  "scan": {
    "hz_lo": 470000000,
    "hz_hi": 608000000,
    "step_hz": 12207.03125,
    "power": [-85.2, -82.1, -90.5, ...]
  }
}
```

| Field | Type | Description |
|-------|------|-------------|
| id | int | Database scan ID |
| timestamp | string | ISO 8601 timestamp |
| band__name | string | Band name |
| scan | object | Full scan data for caching |

**QoS:** 0
**Retain:** false
**Publisher:** MQTT Bridge only

### spectrum/commands/{uuid}/start

Start scanning command. Empty payload.

```json
{}
```

**Publisher:** Server frontend (users)
**Subscriber:** Scanner

### spectrum/commands/{uuid}/stop

Stop scanning command. Empty payload.

```json
{}
```

**Publisher:** Server frontend (users)
**Subscriber:** Scanner

### spectrum/commands/{uuid}/bands

Update band enabled states. Scanner applies changes and republishes to config topic.

```json
[
  {"name": "UHF", "start_hz": 470000000, "stop_hz": 608000000, "enabled": true},
  {"name": "WiFi 2.4", "start_hz": 2400000000, "stop_hz": 2500000000, "enabled": false}
]
```

| Field | Type | Description |
|-------|------|-------------|
| name | string | Band name (must match existing band) |
| start_hz | int | Start frequency in Hz |
| stop_hz | int | Stop frequency in Hz |
| enabled | boolean | Whether band should be scanned |

**Publisher:** Server frontend (users)
**Subscriber:** Scanner

### spectrum/commands/{uuid}/gain

Update receiver gain settings. Scanner applies and republishes to config topic.

```json
{
  "rx_gain": 40,
  "rx_gain_mode": "manual"
}
```

| Field | Type | Description |
|-------|------|-------------|
| rx_gain | float | Gain value in dB (0-73 for Pluto) |
| rx_gain_mode | string | `manual`, `slow_attack`, `fast_attack`, or `hybrid` |

**Publisher:** Server frontend (users)
**Subscriber:** Scanner

## Authentication

All MQTT connections require authentication via the mosquitto-go-auth plugin, which forwards auth requests to Django.

### Client Types

| Type | Username | Password | Description |
|------|----------|----------|-------------|
| Scanner | Scanner UUID | Scanner auth_token | Hardware scanner devices |
| User | User mqtt_id (UUID) | User auth_token | Browser clients |
| Bridge | MQTT_BRIDGE_USERNAME | MQTT_BRIDGE_PASSWORD | Internal service |

### Auth Flow

1. Client connects with username/password
2. Mosquitto calls Django `/api/auth/mqtt/` (POST)
3. Django validates credentials against database
4. Returns 200 (allowed) or 403 (denied)

### Django Auth Endpoint

**POST /api/auth/mqtt/**

Form data:
- `username`: UUID string
- `password`: Auth token

Response: 200 OK or 403 Forbidden

## Access Control (ACL)

Topic permissions are checked via Django for each publish/subscribe.

### ACL Flow

1. Client attempts to publish/subscribe
2. Mosquitto calls Django `/api/auth/mqtt/acl/` (POST)
3. Django checks permissions based on client type
4. Returns 200 (allowed) or 403 (denied)

### Django ACL Endpoint

**POST /api/auth/mqtt/acl/**

Form data:
- `username`: UUID string
- `topic`: MQTT topic
- `acc`: Access type (1=read/subscribe, 2=write/publish)

Response: 200 OK or 403 Forbidden

### Permission Matrix

| Client Type | Topic Pattern | Subscribe | Publish |
|-------------|---------------|-----------|---------|
| Scanner | `spectrum/scanners/{own-uuid}/*` | ✓ | ✓ |
| Scanner | `spectrum/commands/{own-uuid}/*` | ✓ | ✗ |
| Scanner | Other topics | ✗ | ✗ |
| User | `spectrum/#` | ✓ | ✗ |
| User | `spectrum/commands/*` | ✗ | ✓ |
| Bridge | `spectrum/scanners/+/scan` | ✓ | ✗ |
| Bridge | `spectrum/scanners/+/status` | ✓ | ✗ |
| Bridge | `spectrum/scanners/+/config` | ✓ | ✗ |
| Bridge | `spectrum/scanners/+/timeline` | ✗ | ✓ |

## Environment Variables

### Django Server

| Variable | Default | Description |
|----------|---------|-------------|
| `MQTT_BROKER_HOST` | `localhost` | Mosquitto hostname |
| `MQTT_BROKER_PORT` | `1883` | Mosquitto port |
| `MQTT_CLIENT_ID` | `spectrum-server` | Bridge client ID |
| `MQTT_TOPIC_PREFIX` | `spectrum` | Topic prefix |
| `MQTT_BRIDGE_USERNAME` | (required) | Bridge service username |
| `MQTT_BRIDGE_PASSWORD` | (required) | Bridge service password |

### Scanner

| Variable | Default | Description |
|----------|---------|-------------|
| `MQTT_BROKER_URL` | `tcp://localhost:1883` | Broker connection URL |
| `SCANNER_ID` | (required) | Scanner UUID from Django |
| `SCANNER_TOKEN` | (required) | Auth token from Django |

## Mosquitto Configuration

The broker uses mosquitto-go-auth plugin for HTTP-based authentication:

```
# mosquitto.conf
listener 1883                          # MQTT for scanners/bridge
listener 9001                          # WebSocket for browsers
protocol websockets

allow_anonymous false
auth_plugin /mosquitto/go-auth.so
auth_opt_backends http

auth_opt_http_host server
auth_opt_http_port 8000
auth_opt_http_getuser_uri /api/auth/mqtt/
auth_opt_http_aclcheck_uri /api/auth/mqtt/acl/
```

## Wildcard Subscriptions

### MQTT Bridge subscribes to:
- `spectrum/scanners/+/scan` - All scan data (stores to DB)
- `spectrum/scanners/+/status` - All status updates
- `spectrum/scanners/+/config` - All config updates

### Frontend subscribes to:
- `spectrum/scanners/+/scan` - Live scan data
- `spectrum/scanners/+/status` - Scanner status
- `spectrum/scanners/+/config` - Scanner configuration
- `spectrum/scanners/+/timeline` - DB storage notifications

## Data Flow

### Live Scan Display

```
Scanner → publish scan → Broker → Frontend (displays immediately)
                              ↓
                        MQTT Bridge (stores every 10s)
                              ↓
                        publish timeline → Broker → Frontend (updates cache)
```

### Historical Playback

1. Frontend loads scan cache via REST API on component mount
2. Timeline updates arrive via MQTT with full scan data
3. Frontend adds new scans to cache automatically
4. Scrubbing uses binary search on local cache (no API calls)

## Scanner ID Format

Scanner IDs are UUIDs generated by Django when creating a scanner in the admin.

Example: `550e8400-e29b-41d4-a716-446655440000`

Legacy format (informational only): `{location}-{type}-{index}` (e.g., `studio-a-pluto-1`)
