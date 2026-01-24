# Pluto Calibration Tool

Calibrates the ADALM-Pluto spectrum scanner using a tinySA Ultra as a reference signal source.

## Overview

This tool measures the Pluto's amplitude accuracy across a frequency range by:
1. Setting the tinySA Ultra to output a known signal level
2. Tuning the Pluto to each frequency and measuring the received power
3. Recording the difference between expected and measured values
4. Outputting calibration data that can be imported into the scanner config

## Requirements

- ADALM-Pluto running maia-httpd
- tinySA Ultra connected via USB
- Direct RF connection between tinySA output and Pluto input (use appropriate attenuator if needed)

## Usage

```bash
# Build the tool
go build -o calibrate ./cmd/calibrate

# Run with defaults (UHF band, -28 dBm reference)
./calibrate

# Custom frequency range and settings
./calibrate -start 450 -stop 700 -step 5 -level -30 -gain 30
```

## Command Line Options

| Flag | Default | Description |
|------|---------|-------------|
| `-tinysa` | `/dev/tty.usbmodem4001` | tinySA serial port |
| `-pluto` | `https://192.168.2.1` | Pluto maia-httpd URL |
| `-output` | `calibration.yaml` | Output file for calibration data |
| `-level` | `-28.0` | Reference signal level in dBm |
| `-gain` | `40.0` | Pluto RX gain during calibration |
| `-start` | `470.0` | Start frequency in MHz |
| `-stop` | `600.0` | Stop frequency in MHz |
| `-step` | `10.0` | Frequency step in MHz |

## Recommended Settings

### Signal Level
Use a level that's well above the noise floor but won't compress the Pluto's front end:
- **-28 to -38 dBm** at gain=30 works well
- Avoid high gain (>40 dB) which can cause compression

### Frequency Step
- **6 MHz steps** align with TV channel boundaries in UHF
- **10 MHz steps** are faster for initial calibration
- **5 MHz steps** for finer calibration

### Gain
- **30 dB** recommended - linear response across power levels
- **40+ dB** can cause compression with stronger signals

## Output Format

The tool outputs a YAML file:

```yaml
reference_dbm: -28
rx_gain: 30
timestamp: 2024-01-23T20:45:19.137612-05:00
points:
  - frequency_mhz: 470
    measured_dbm: -27.5
  - frequency_mhz: 480
    measured_dbm: -27.8
  # ... more points
```

## Importing into Config

Copy the calibration section into your `config.yaml`:

```yaml
backend:
  type: pluto
  url: https://192.168.2.1

calibration:
  reference_dbm: -28
  rx_gain: 30
  points:
    - frequency_mhz: 470
      measured_dbm: -27.5
    - frequency_mhz: 480
      measured_dbm: -27.8
    # ... paste remaining points from calibration.yaml
```

Or keep calibration in a separate file and reference it (if supported).

## How Calibration is Applied

The scanner computes a correction factor for each frequency:

```
correction = reference_dbm - measured_dbm
```

For frequencies between calibration points, linear interpolation is used.

Example:
- Reference: -28 dBm
- Measured at 470 MHz: -27.5 dBm
- Correction: -28 - (-27.5) = -0.5 dB
- Scanner subtracts 0.5 dB from readings at 470 MHz

## Troubleshooting

### No signal detected
- Check RF cable connection
- Verify tinySA is in output mode
- Try higher reference level (-20 dBm)

### Readings vary wildly
- Add attenuator if signal is too strong
- Reduce Pluto gain
- Check for interference

### Non-linear response
- Reduce gain to 30 dB
- Use lower reference level (-38 dBm)