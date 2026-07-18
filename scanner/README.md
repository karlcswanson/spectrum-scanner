# Scanner

Go-based spectrum scanner supporting multiple backends (ADALM-Pluto, OWON, tinySA Ultra). Provides both a CLI/web server and a Wails desktop application.

## Prerequisites

- Go 1.22+
- Node.js 18+ and npm
- [Wails v2](https://wails.io/) (for desktop app only)

## Quick Start

```bash
# Install dependencies
make tidy
cd ../frontend && npm install && cd ../scanner

# Run CLI scanner (connects to Pluto at 192.168.2.1)
make dev
```

## CLI Scanner

Runs a web server with embedded Vue frontend at `http://localhost:8080`.

### Usage

```bash
./scanner [flags]
  -listen string   HTTP listen address (default ":8080")
  -addr string     Backend address (IP, URL, or serial port)
  -backend string  Backend type: pluto, owon, tinysa
  -config string   Config file path
  -auto-start      Start scanning on startup
```

### Examples

```bash
# Pluto via USB network (default)
go run ./cmd/scanner -config config.yaml

# Pluto with explicit address
go run ./cmd/scanner -backend pluto -addr https://192.168.2.1

# OWON spectrum analyzer
go run ./cmd/scanner -backend owon -addr 10.10.125.155

# tinySA Ultra
go run ./cmd/scanner -backend tinysa -addr /dev/tty.usbmodem4001

# Custom port with auto-start
go run ./cmd/scanner -listen :9000 -auto-start
```

### Environment Variables

| Variable | Description |
|----------|-------------|
| `SCANNER_LISTEN` | HTTP listen address |
| `SCANNER_BACKEND` | Backend type |
| `SCANNER_ADDR` | Backend address |
| `SCANNER_ID` | Device UUID |
| `SCANNER_NAME` | Display name |

### Building for ADALM-Pluto

```bash
# Build ARM binary
make build-arm

# Deploy to Pluto via SSH
make deploy

# Deploy with auto-start service
make deploy-service
```

## Desktop App (Wails)

Native desktop application with the same functionality as the CLI scanner.

### Development

```bash
# Install frontend dependencies (first time)
make desktop-deps

# Run with hot reload
make desktop-dev
```

### Production Build

```bash
make desktop           # Current platform
make desktop-mac       # macOS universal
make desktop-windows   # Windows amd64
make desktop-linux     # Linux amd64
```

Output: `cmd/desktop/build/bin/`

## Backends

### ADALM-Pluto

Uses [maia-sdr](https://maia-sdr.org)'s FPGA-accelerated FFT for wideband sweeps.

**Prerequisites:** Flash maia-sdr firmware to your Pluto. See [maia-sdr installation guide](https://maia-sdr.org/installation/).

Default address: `192.168.2.1`. Ethernet Compatibility Mode may need to be changed depending on platform. See [Pluto customization guide](https://wiki.analog.com/university/tools/pluto/users/customizing) for network settings.

```yaml
backend:
  type: pluto
  url: "https://192.168.2.1"
```

| Setting | Description |
|---------|-------------|
| `url` | maia-httpd URL (default: `https://192.168.2.1`) |
| `rx_gain` | RX gain 0-73 dB (default: 40) |
| `rx_gain_mode` | `manual`, `slow_attack`, `fast_attack` |

**Calibration:** The Pluto's amplitude readings can be calibrated against a known reference signal. See [cmd/calibrate/README.md](cmd/calibrate/README.md) for the calibration procedure.

### OWON HSA1000

Connects via SCPI over TCP.

```yaml
backend:
  type: owon
  address: "10.10.125.155"
  port: 1015
  rbw: 10000
  vbw: 0
  attenuation_db: 10
```

### tinySA Ultra

Connects via USB serial at 576000 baud.

```yaml
backend:
  type: tinysa
  address: "/dev/tty.usbmodem4001"
  rbw: 10000
  attenuation_db: 0
```

| Setting | Description |
|---------|-------------|
| `rbw` | Resolution bandwidth: 3000, 10000, 30000, 100000, 300000, 600000 Hz |
| `attenuation_db` | Input attenuation 0-31 dB |

## Configuration

Config file discovery order:
1. `-config` flag
2. `./config.yaml`
3. System config directory (`~/Library/Application Support/Spectrum Scanner/config.yaml`)
4. Default configuration

### Example Config

```yaml
device_id: "studio-a-scanner"
name: "Studio A Scanner"
auto_start: true
dwell_time_ms: 50

backend:
  type: pluto
  url: "https://192.168.2.1"

bands:
  - name: UHF
    start_mhz: 470
    stop_mhz: 608
    enabled: true

  - name: WiFi 2.4
    start_mhz: 2400
    stop_mhz: 2500
    enabled: false

mqtt:
  enabled: true
  broker: "tcp://mqtt.example.com:1883"
  id: "scanner-uuid"
  token: "auth-token"
```

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/status` | Scanner status |
| GET | `/api/config` | Current configuration |
| PUT | `/api/config` | Update configuration |
| GET | `/api/bands` | Configured bands |
| PUT | `/api/bands` | Update bands |
| POST | `/api/scan/start` | Start scanning |
| POST | `/api/scan/stop` | Stop scanning |
| GET | `/ws/stream` | WebSocket for live data |
| GET | `/api/scans/timeline` | Historical scan timeline |
| GET | `/api/scans/at-time` | Scan at specific time |
| GET | `/health` | Health check |

### WebSocket Data Format

```json
{
  "id": "scanner-uuid",
  "timestamp": "2024-01-15T10:30:00Z",
  "hz_lo": 470000000,
  "hz_hi": 608000000,
  "step": 15000,
  "samples": 9200,
  "power": [-85.2, -87.1, -82.5]
}
```

## Makefile Reference

```bash
make help            # Show all commands
make dev             # Run CLI scanner locally
make build           # Build CLI binary
make build-arm       # Build for Pluto (ARM)
make deploy          # Deploy to Pluto via SSH
make desktop-dev     # Run desktop app with hot reload
make desktop         # Build desktop app
```

## Code Structure

```
scanner/
├── cmd/
│   ├── scanner/      # CLI entry point
│   ├── desktop/      # Wails desktop app
│   └── calibrate/    # Pluto calibration tool
├── internal/
│   ├── api/          # HTTP server + WebSocket
│   ├── backend/      # Hardware backends
│   │   ├── pluto/    # ADALM-Pluto
│   │   ├── owon/     # OWON spectrum analyzer
│   │   └── tinysa/   # tinySA Ultra
│   ├── config/       # Configuration management
│   ├── db/           # SQLite scan history
│   ├── models/       # Data structures
│   ├── mqtt/         # MQTT publishing
│   └── scanner/      # Core scanning engine
└── Makefile
```
