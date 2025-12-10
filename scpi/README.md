# Spectrum SCPI CLI

Command-line tool for connecting TTi, OWON, or generic SCPI spectrum analyzers to Spectrum Server.

## Installation

```bash
cd scpi
pip install -e .
```

## Usage

### Identify Analyzer

```bash
spectrum-scpi identify --resource "TCPIP::192.168.1.100::INSTR" --type tti
```

### Single Scan

```bash
spectrum-scpi scan \
  --resource "TCPIP::192.168.1.100::INSTR" \
  --type tti \
  --start 470 \
  --stop 608 \
  --band UHF
```

### Continuous Scanning with MQTT

```bash
spectrum-scpi continuous \
  --resource "TCPIP::192.168.1.100::INSTR" \
  --type tti \
  --start 470 \
  --stop 608 \
  --band UHF \
  --interval 5 \
  --mqtt-host localhost \
  --scanner-id bench-tti-1 \
  --scanner-name "Bench TTi Analyzer" \
  --location "RF Lab"
```

## Supported Analyzers

- **TTi PSA Series** (`--type tti`)
- **OWON XSA/HSA Series** (`--type owon`)
- **Generic SCPI** (`--type generic`)

## VISA Resource Names

Examples:
- TCP/IP: `TCPIP::192.168.1.100::INSTR`
- USB: `USB0::0x1AB1::0x0588::DS1ZA123456789::INSTR`
- Serial: `ASRL/dev/ttyUSB0::INSTR`
