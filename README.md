# Spectrum Scanner

A wideband RF spectrum scanner for the ADALM-Pluto SDR, designed for live event frequency coordination.

## Overview

This project provides a sweep-based spectrum scanner that leverages [maia-sdr](https://maia-sdr.org)'s FPGA-accelerated signal processing to scan wide frequency bands efficiently. It's designed for RF coordination in live events: wireless microphones (UHF), in-ear monitors, WiFi, DECT intercoms, and business radio.

## Architecture

```
┌─────────────────── ADALM Pluto ───────────────────┐
│                                                    │
│  ┌────────────┐   ┌─────────────────────────────┐ │
│  │ maia-hdl   │──▶│ maia-httpd (port 8080)      │ │
│  │ (FPGA FFT) │   │ - AD9361 control            │ │
│  └────────────┘   │ - Waterfall WebSocket       │ │
│                   └───────────────┬─────────────┘ │
│                                   │               │
│                   ┌───────────────▼─────────────┐ │
│                   │ spectrum-scanner (port 80)  │ │
│                   │ - Sweep orchestration       │ │
│                   │ - Band stitching            │ │
│                   │ - Web UI + WebSocket API    │ │
│                   └─────────────────────────────┘ │
└───────────────────────────────────────────────────┘
```

## Features

- **Wideband sweeping**: Scans 20 MHz segments and stitches them together
- **Configurable bands**: UHF (470-608 MHz), WiFi 2.4 GHz, DECT, Business Radio
- **Real-time display**: Live spectrum via WebSocket
- **REST API**: Control scanning via HTTP
- **Embedded UI**: Single-page web interface served from the device
- **Cross-platform**: Runs on Mac/Linux for development, ARM for deployment

## Prerequisites

- ADALM-Pluto with [maia-sdr firmware](https://maia-sdr.org/installation/)
- Go 1.23+ (for building)

## Quick Start

### Development (on your Mac)

```bash
# Connect Pluto via USB (default IP: 192.168.2.1)
make check-pluto

# Run scanner locally, connecting to Pluto
make dev

# Open browser
open http://localhost:8080
```

### Production (on the Pluto)

```bash
# Cross-compile for ARM
make build-arm

# Deploy to Pluto
make deploy

# SSH in and run
ssh root@192.168.2.1
/usr/bin/spectrum-scanner -listen :80 -maia http://localhost:8080

# Or deploy with auto-start service
make deploy-service
```

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/status` | Scanner status (online, scanning, current band) |
| GET | `/api/config` | Full configuration |
| PUT | `/api/config` | Update configuration |
| GET | `/api/bands` | List configured bands |
| PUT | `/api/bands` | Update band list |
| POST | `/api/scan/start` | Start scanning |
| POST | `/api/scan/stop` | Stop scanning |
| GET | `/ws/stream` | WebSocket for live scan data |
| GET | `/health` | Health check |

## WebSocket Data Format

Scan results are sent as JSON over the `/ws/stream` WebSocket:

```json
{
  "id": "scanner-uuid",
  "timestamp": "2024-01-15T10:30:00Z",
  "hz_lo": 470000000,
  "hz_hi": 608000000,
  "step": 15000,
  "samples": 9200,
  "power": [-85.2, -87.1, -82.5, ...]
}
```

This format is compatible with the existing spectrum-frontend Vue application.

## Configuration

Configuration can be provided via:

1. **Command line flags**: `-listen`, `-maia`, `-config`, `-auto-start`
2. **Environment variables**: `SCANNER_LISTEN`, `SCANNER_MAIA_URL`, `SCANNER_ID`, `SCANNER_NAME`
3. **Config file**: JSON file passed via `-config`

### Default Bands

| Band | Frequency Range | Default |
|------|-----------------|---------|
| UHF | 470 - 608 MHz | Enabled |
| Business Radio | 450 - 470 MHz | Disabled |
| DECT | 1920 - 1930 MHz | Disabled |
| WiFi 2.4 | 2400 - 2500 MHz | Disabled |

### Example Config File

```json
{
  "device_id": "studio-a-scanner",
  "name": "Studio A",
  "description": "Main rehearsal studio",
  "dwell_time_ms": 50,
  "mode": "Average",
  "bands": [
    {"name": "UHF", "start_hz": 470000000, "stop_hz": 608000000, "enabled": true},
    {"name": "IEM", "start_hz": 470000000, "stop_hz": 608000000, "enabled": true}
  ]
}
```

## Project Structure

```
spectrum-scanner/
├── cmd/scanner/main.go       # Entry point
├── internal/
│   ├── api/                  # HTTP server, handlers, WebSocket
│   ├── config/               # Configuration management
│   ├── maia/                 # maia-httpd client
│   ├── models/               # Data structures
│   └── sweep/                # Sweep orchestration engine
├── web/                      # Vue frontend (future)
├── Makefile
└── README.md
```

## Future Plans

- **Phase 2**: MQTT publishing for central server aggregation
- **Central Dashboard**: View multiple scanners from different locations
- **Peak hold**: Rolling maximum display
- **Export**: CSV/JSON export of scan data

## License

MIT
