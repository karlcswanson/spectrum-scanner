# Spectrum Scanner

Go-based spectrum scanner that interfaces with ADALM-Pluto SDR via maia-sdr. Provides both a standalone CLI/web server and a Wails desktop application.

## Architecture

```
scanner/
├── cmd/
│   ├── scanner/      # CLI scanner with embedded web UI
│   └── desktop/      # Wails desktop application
├── internal/
│   ├── api/          # HTTP API server + embedded frontend
│   ├── db/           # SQLite scan history storage
│   ├── maia/         # maia-sdr client
│   ├── models/       # Shared data models
│   ├── mqtt/         # MQTT client for central server
│   └── scanner/      # Core scanning engine
└── Makefile
```

## Prerequisites

- Go 1.22+
- Node.js 18+ and npm
- [Wails v2](https://wails.io/) (for desktop app)
- ADALM-Pluto with [maia-sdr](https://github.com/maia-sdr/maia-sdr) firmware

## Quick Start

```bash
# Install dependencies
make tidy
cd ../frontend && npm install

# Run CLI scanner in dev mode (connects to Pluto at 192.168.2.1)
make dev
```

## CLI Scanner

The CLI scanner runs a web server with embedded Vue frontend, providing spectrum visualization at `http://localhost:8080`.

### Development

```bash
# Run locally (connects to Pluto, auto-starts scanning)
make dev

# Or run directly with custom options
go run ./cmd/scanner \
  -listen :8080 \
  -addr https://192.168.2.1 \
  -config ../config.yaml
```

### Production Build

```bash
# Build for local machine
make build
./bin/scanner -listen :8080 -addr https://192.168.2.1

# Build with embedded frontend
make build-frontend  # builds Vue app and embeds in Go binary
make build           # compile Go binary

# Or use the combined command
make build-all       # builds frontend + ARM binary for Pluto
```

### Cross-compile for ADALM-Pluto

```bash
# Build ARM binary for Pluto
make build-arm

# Deploy to Pluto via SSH
make deploy

# Deploy with auto-start service
make deploy-service
```

## Desktop App (Wails)

The Wails desktop app provides a native application with the same functionality.

### Development

```bash
# Install frontend dependencies (first time only)
make desktop-deps

# Run in development mode with hot reload
make desktop-dev

# Or directly
cd cmd/desktop && wails dev
```

In dev mode:
- Frontend hot-reloads on changes to `cmd/desktop/frontend/src/`
- Go backend rebuilds on changes to `*.go` files
- DevTools available via right-click menu

### Production Build

```bash
# Build for current platform
make desktop

# Build for specific platforms
make desktop-mac      # macOS universal binary
make desktop-windows  # Windows amd64
make desktop-linux    # Linux amd64

# Or directly with wails
cd cmd/desktop && wails build -platform darwin/universal
```

Built binaries are output to `cmd/desktop/build/bin/`.

## Frontend Development

The frontend source is in `/frontend` (shared between central server and scanner).

### Standalone Frontend (for CLI scanner)

```bash
cd ../frontend

# Development with hot reload (proxies API to localhost:8080)
npm run dev:standalone

# Production build
npm run build:standalone

# Build and copy to scanner embed directory
npm run build:scanner
```

### Desktop Frontend (for Wails app)

The Wails app uses a symlinked copy of the frontend in `cmd/desktop/frontend/`. Changes to the shared components in `/frontend/src/components/` are automatically available.

```bash
# From scanner directory
make desktop-dev  # runs wails dev with hot reload
```

## Configuration

Both CLI and Wails use the same config discovery:

1. `./config.yaml` (current directory)
2. System config directory:
   - macOS: `~/Library/Application Support/Spectrum Scanner/config.yaml`
   - Linux: `~/.config/Spectrum Scanner/config.yaml`
   - Windows: `%AppData%/Spectrum Scanner/config.yaml`
3. Default configuration if no file found

### Config File Format

```yaml
auto_start: true
dwell_time_ms: 200

bands:
  - name: "UHF TV"
    start_mhz: 470
    stop_mhz: 608
    enabled: true

  - name: "WiFi 2.4GHz"
    start_mhz: 2400
    stop_mhz: 2500
    enabled: false

mqtt:
  enabled: true
  broker: "tcp://mqtt.example.com:1883"
  id: "scanner-uuid"
  token: "auth-token"
```

### CLI Flags

```bash
./scanner [flags]
  -listen string   HTTP listen address (default ":8080")
  -addr string     Backend address (IP or URL)
  -backend string  Backend type: pluto, owon
  -config string   Config file path (explicit)
```

## API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /api/status` | Scanner status |
| `GET /api/config` | Current configuration |
| `PUT /api/config` | Update configuration |
| `POST /api/scan/start` | Start scanning |
| `POST /api/scan/stop` | Stop scanning |
| `GET /api/bands` | Get configured bands |
| `GET /ws/stream` | WebSocket for live scan data |
| `GET /api/scans/timeline` | Historical scan timeline |
| `GET /api/scans/at-time` | Fetch scan at specific time |
| `GET /api/scans/decimated` | Decimated scans for scrubber preview |

## Makefile Reference

```bash
make help  # Show all available commands
```

Key commands:
- `make dev` - Run locally with Pluto connection
- `make build` - Build CLI binary
- `make build-frontend` - Build and embed Vue frontend
- `make desktop-dev` - Run Wails app in dev mode
- `make desktop` - Build Wails app for current platform
- `make deploy` - Deploy to Pluto via SSH
