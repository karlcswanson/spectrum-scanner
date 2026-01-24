# Spectrum Scanner

A wideband RF spectrum scanner supporting multiple backends (ADALM-Pluto, OWON spectrum analyzers, tinySA Ultra), designed for live event frequency coordination.

## Overview

This project provides a sweep-based spectrum scanner that can use different hardware backends to scan wide frequency bands. It's designed for RF coordination in live events: wireless microphones (UHF), in-ear monitors, WiFi, DECT intercoms, and business radio.

**Supported Backends:**
- **ADALM-Pluto** - Uses [maia-sdr](https://maia-sdr.org)'s FPGA-accelerated signal processing
- **OWON HSA1000 series** - Via SCPI over TCP
- **tinySA Ultra** - Via USB serial

## Architecture (Pluto Backend)

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

- **Multiple backends**: ADALM-Pluto (via maia-sdr) or OWON spectrum analyzers
- **Wideband sweeping**: Scans segments and stitches them together
- **Configurable bands**: UHF (470-608 MHz), WiFi 2.4 GHz, DECT, Business Radio
- **Real-time display**: Live spectrum via WebSocket
- **REST API**: Control scanning via HTTP
- **Embedded UI**: Single-page web interface served from the device
- **MQTT publishing**: Send scan data to a central server
- **Cross-platform**: Runs on Mac/Linux for development, ARM for deployment

## Prerequisites

- Go 1.23+ (for building)
- For Pluto backend: ADALM-Pluto with [maia-sdr firmware](https://maia-sdr.org/installation/)
- For OWON backend: OWON HSA1000 series connected via network

## Quick Start

### Development (on your Mac)

```bash
# With ADALM-Pluto via USB (default IP: 192.168.2.1)
go run ./cmd/scanner -config config.yaml

# With OWON spectrum analyzer
go run ./cmd/scanner -backend owon -addr 10.10.125.155 -config config.yaml

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
/usr/bin/spectrum-scanner -listen :80 -addr https://localhost -config /etc/spectrum-scanner.yaml

# Or deploy with auto-start service
make deploy-service
```

## Command Line Reference

```
Usage: spectrum-scanner [options]

Options:
  -listen string    HTTP listen address (default ":8080")
  -backend string   Backend type: pluto, owon, tinysa (overrides config)
  -addr string      Backend address - IP or URL (overrides config)
  -config string    Config file path (YAML or JSON)
  -auto-start       Automatically start scanning on startup
```

### Examples

```bash
# Pluto via USB network (default address)
go run ./cmd/scanner -config config.yaml

# Pluto with explicit address
go run ./cmd/scanner -backend pluto -addr https://192.168.2.1 -config config.yaml

# OWON spectrum analyzer
go run ./cmd/scanner -backend owon -addr 10.10.125.155 -config config.yaml

# tinySA Ultra
go run ./cmd/scanner -backend tinysa -addr /dev/tty.usbmodem4001 -config config.yaml

# Custom listen port
go run ./cmd/scanner -listen :9000 -config config.yaml

# Auto-start scanning
go run ./cmd/scanner -auto-start -config config.yaml
```

## Environment Variables

Environment variables override command line flags:

| Variable | Description |
|----------|-------------|
| `SCANNER_LISTEN` | HTTP listen address (e.g., `:8080`) |
| `SCANNER_BACKEND` | Backend type: `pluto` or `owon` |
| `SCANNER_ADDR` | Backend address (IP or URL) |
| `SCANNER_ID` | Device ID (UUID) |
| `SCANNER_NAME` | Human-readable scanner name |
| `SCANNER_DESCRIPTION` | Scanner description |

## Configuration File

Configuration files can be YAML or JSON. YAML is recommended for readability.

### Full YAML Example

```yaml
# Scanner identity
device_id: "studio-a-scanner"    # UUID, auto-generated if not set
name: "Studio A Scanner"
description: "Main rehearsal studio"

# Scan settings
auto_start: true                  # Start scanning on boot
dwell_time_ms: 50                 # Time per sweep segment
mode: Average                     # Average or PeakDetect

# Gain settings (Pluto backend)
rx_gain: 40                       # RX gain in dB (0-73)
rx_gain_mode: manual              # manual, slow_attack, or fast_attack

# Backend configuration
backend:
  type: pluto                     # pluto or owon
  url: "https://192.168.2.1"      # For Pluto: maia-httpd URL
  # For OWON:
  # type: owon
  # address: "10.10.125.155"      # IP address
  # port: 1015                    # SCPI port (default: 1015)
  # rbw: 10000                    # Resolution bandwidth (Hz), 0 = auto
  # vbw: 0                        # Video bandwidth (Hz), 0 = auto
  # attenuation_db: 10            # Input attenuation (0-40 dB)

  # For tinySA Ultra:
  # type: tinysa
  # address: "/dev/tty.usbmodem4001"  # Serial port
  # rbw: 10000                    # Resolution bandwidth (Hz): 3000, 10000, 30000, 100000, 300000, 600000
  # attenuation_db: 0             # Input attenuation (0-31 dB)

# Frequency bands to scan
bands:
  - name: UHF
    start_mhz: 470
    stop_mhz: 608
    enabled: true

  - name: Business Radio
    start_mhz: 450
    stop_mhz: 470
    enabled: false

  - name: DECT
    start_mhz: 1920
    stop_mhz: 1930
    enabled: false

  - name: WiFi 2.4
    start_mhz: 2400
    stop_mhz: 2500
    enabled: false

# MQTT publishing (optional)
mqtt:
  enabled: true
  broker: "tcp://mqtt.example.com:1883"
  id: "uuid-from-server"          # Scanner UUID from Django admin
  token: "auth-token"             # Auth token from Django admin
  name: "Studio A Scanner"        # Display name
  location: "Studio A"            # Physical location
  topic_prefix: "spectrum"        # Topic prefix (default: spectrum)
```

### Default Bands

| Band | Frequency Range | Default |
|------|-----------------|---------|
| UHF | 470 - 608 MHz | Enabled |
| Business Radio | 450 - 470 MHz | Disabled |
| DECT | 1920 - 1930 MHz | Disabled |
| WiFi 2.4 | 2400 - 2500 MHz | Disabled |

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

## Project Structure

```
spectrum-scanner/
├── cmd/scanner/main.go       # Entry point
├── config.yaml               # Example configuration
├── config/                   # Additional config examples
│   └── owon-example.yaml
├── internal/
│   ├── api/                  # HTTP server, handlers, WebSocket
│   ├── backend/              # Hardware backends
│   │   ├── owon/             # OWON spectrum analyzer
│   │   ├── pluto/            # ADALM-Pluto via maia-sdr
│   │   └── tinysa/           # tinySA Ultra via USB serial
│   ├── config/               # Configuration management
│   ├── models/               # Data structures
│   ├── mqtt/                 # MQTT publishing
│   └── scanner/              # Sweep orchestration engine
├── frontend/                 # Vue frontend
├── server/                   # Django backend (central server)
├── Makefile
└── README.md
```

## Backend Details

### ADALM-Pluto (via maia-sdr)

Uses maia-sdr's FPGA-accelerated FFT for fast wideband sweeps. The scanner connects to maia-httpd running on the Pluto.

- Default URL: `https://192.168.2.1` (USB network)
- On-device: `https://localhost`

### OWON HSA1000 Series

Connects to OWON spectrum analyzers via SCPI over TCP.

- Default port: 1015
- Supports configurable RBW, VBW, and attenuation

### tinySA Ultra

Connects to tinySA Ultra via USB serial at 576000 baud.

- Frequency range: 100 kHz - 5.3 GHz
- 450 points per sweep
- Supports configurable RBW and attenuation
- Automatic chunking for high-resolution scans

## License

MIT
