# MQTT Topic Structure

## Topic Hierarchy

```
spectrum/
├── scanners/
│   └── {scanner-id}/
│       ├── scan              # Scan data (JSON, see scan.json schema)
│       ├── status            # Scanner status (online, scanning, current band)
│       └── config            # Current configuration
│
├── commands/
│   └── {scanner-id}/
│       ├── start             # Start scanning
│       ├── stop              # Stop scanning
│       └── configure         # Update configuration (JSON payload)
│
└── server/
    └── announce              # Server presence/heartbeat
```

## Message Formats

### spectrum/scanners/{id}/scan

Minimal scan data, published after each band sweep completes.

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

**QoS:** 0 (at most once) - scans are frequent, losing one is acceptable
**Retain:** false

### spectrum/scanners/{id}/status

```json
{
  "online": true,
  "scanning": true,
  "current_band": "UHF"
}
```

**QoS:** 1 (at least once)
**Retain:** true - so new subscribers see current status

### spectrum/scanners/{id}/config

Full scanner configuration, published on connect and config changes.

```json
{
  "id": "studio-a-pluto-1",
  "name": "Studio A Scanner",
  "type": "pluto",
  "location": "Studio A",
  "description": "ADALM-Pluto Scanner",
  "bands": [
    {"name": "UHF", "start_hz": 470000000, "stop_hz": 608000000, "enabled": true},
    {"name": "WiFi 2.4", "start_hz": 2400000000, "stop_hz": 2500000000, "enabled": false}
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

### spectrum/commands/{id}/start

Empty payload or:
```json
{"bands": ["UHF", "WiFi 2.4"]}
```

### spectrum/commands/{id}/stop

Empty payload.

### spectrum/commands/{id}/configure

Same format as config status message. Scanner applies changes and republishes to status.

## Scanner ID Format

Recommended format: `{location}-{type}-{index}`

Examples:
- `studio-a-pluto-1`
- `main-stage-tti-1`
- `foh-owon-1`

## Wildcard Subscriptions

Server subscribes to:
- `spectrum/scanners/+/scan` - All scan data
- `spectrum/scanners/+/status` - All status updates

Dashboard subscribes to:
- `spectrum/scanners/{specific-id}/#` - Everything from one scanner
