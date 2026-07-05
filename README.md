# Spectrum Scanner

![Built with Claude](https://img.shields.io/badge/Built_with-Claude-D97757?style=for-the-badge&logo=claude&logoColor=white)


Multi-band RF spectrum monitor for frequency coordination.

## Features

* **Multi-band Scanning** - The ADALM-Pluto has a frequency range of 70 MHz - 6 GHz when setup in AD9364 mode. It has been tested across the LMR, UHF, DECT, and 2.4 GHz bands.
* **Standalone Desktop App** - For Mac / Windows.
* **Embedded Client** - Run headless via Raspberry Pi / GL-Inet Routers.
* **Central Server** *(optional)* - Compare and download scans from a fleet of scanners. The server can be hosted locally or in the cloud.
* **Multi-Zone Coverage** - Compare scan data from multiple scanners across large events, festival grounds, or rehearsal studios.
* **Scan History** - Scrub back and forth to visualize scans over time.
* **Calibration** - Generate a calibration curve for the Pluto based on TinySA signal generator output.


## Demo
https://github.com/user-attachments/assets/11c4eb5d-948d-4720-abb7-279548c8aace

## Screenshots
![Overview](docs/img/overview.png)
![Login](docs/img/login.png)


## Supported Hardware

| Backend | Description | Connection |
|---------|-------------|-----------|
| **ADALM-Pluto** | FPGA-accelerated via [maia-sdr](https://maia-sdr.org) | USB |
| **OWON HSA1000** | Spectrum analyzer via SCPI | TCP/IP |
| **tinySA Ultra** | Portable analyzer | USB |

## Architecture

```mermaid
flowchart TD
    subgraph MS["Main Stage"]
        S1[Scanner]
    end

    subgraph BC["Broadcast Compound"]
        S2[Scanner]
    end

    subgraph FOH["FOH"]
        S3[Scanner]
    end

    LC[Local Client]

    subgraph Server["spectrum-server"]
        MQ[Mosquitto<br/>MQTT Broker]
        BR[MQTT Bridge]
        DB[(Database)]
        DJ[Django<br/>REST API]
    end

    V[Browser Client]

    S3 --- LC
    S1 & S2 & S3 ---|MQTT| MQ
    MQ --- BR
    BR --- DB
    DJ --- DB
    DJ ---|REST| V
    MQ ---|WebSocket| V
```

## Project Structure

```
spectrum-scanner/
├── scanner/              # Go scanner (CLI + Desktop app)
│   ├── cmd/scanner/      # CLI with embedded web UI
│   ├── cmd/desktop/      # Wails desktop application
│   ├── cmd/calibrate/    # Pluto calibration tool
│   └── internal/         # Backend implementations
├── server/               # Django central server + deployment
│   ├── api/              # REST API
│   ├── realtime/         # MQTT bridge
│   └── docker-compose.*  # Docker deployment
└── frontend/             # Vue.js frontend (shared)
```

## Quick Start

### Standalone Scanner

Run a scanner with local web UI at `http://localhost:8080`:

```bash
cd scanner

# With ADALM-Pluto
go run ./cmd/scanner -config ../config.yaml

# With OWON spectrum analyzer
go run ./cmd/scanner -backend owon -addr 10.10.125.155

# With tinySA Ultra
go run ./cmd/scanner -backend tinysa -addr /dev/tty.usbmodem4001
```

### Desktop App

```bash
cd scanner
make desktop-dev
```

### Central Server

```bash
cd server

# Development
docker compose up -d

# Production
docker compose -f docker-compose.prod.yml up -d --build
```

## Documentation

| Component | README |
|-----------|--------|
| Scanner (CLI + Desktop) | [scanner/README.md](scanner/README.md) |
| Central Server | [server/README.md](server/README.md) |
| Calibration Tool | [scanner/cmd/calibrate/README.md](scanner/cmd/calibrate/README.md) |

## Default Frequency Bands

| Band | Frequency Range | Use Case           |
|------|-----------------|--------------------|
| VHF | 174 - 216 MHz | Wireless mics, IEMs (VHF high) |
| Business Radio | 450 - 470 MHz | Two-way radios     |
| UHF | 470 - 636 MHz | Wireless mics, IEMs |
| 900 MHz ISM | 902 - 928 MHz | Unlicensed mic gear |
| STL | 944 - 960 MHz | Studio-transmitter link |
| DECT | 1920 - 1930 MHz | Intercom           |
| WiFi 2.4 | 2400 - 2500 MHz | WiFi, Intercom     |

Bands are defined once in `spectrum-ios/SpectrumScanner/Models/Models.swift`
(`Band.defaultBands`); keep the scanner/server defaults in sync with that list.

## License

MIT
