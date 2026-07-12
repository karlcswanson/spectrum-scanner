# Pluto Calibration Tool

Calibrates the ADALM-Pluto spectrum scanner using a tinySA Ultra as a reference signal source.

## Overview

This tool measures the Pluto's amplitude accuracy across one or more frequency
bands by:
1. Setting the tinySA Ultra to output a known signal level
2. Sweeping each band, tuning the Pluto to every step and measuring received power
3. Averaging any frequencies shared between adjacent bands and sorting the result
4. Writing calibration data as **YAML** (paste into `config.yaml`) and **JSON**
   (for the iOS client, byte-compatible with the server's REST endpoint)

## Requirements

- ADALM-Pluto running maia-httpd
- tinySA Ultra connected via USB
- Direct RF connection between tinySA output and Pluto input (use appropriate attenuator if needed)

## Usage

```bash
# Build the tool
go build -o calibrate ./cmd/calibrate

# Run with defaults: sweeps the full iOS band set at -28 dBm, gain 30
./calibrate

# Custom bands (repeat -band as needed), level and gain
./calibrate -band 450:470:5 -band 470:636:6:UHF -level -30 -gain 30

# With a 20 dB inline attenuator between tinySA and Pluto
./calibrate -pad 20
```

With a direct cable from the tinySA **RF/LOW** port, `./calibrate` with no flags
is the recommended path. The defaults are tuned to produce a good calibration
out of the box (`-28` dBm, gain `30`).

### Scope: low-output bands only (≤ 800 MHz)

The tinySA Ultra produces a clean sine signal up to 800 MHz from its **RF/LOW**
port. Above that it switches to a square-wave **high output** on the separate
**CAL/HIGH** connector — a different physical port, with a documented risk of
damaging the low-input attenuator if both ports stay connected. To keep this a
simple, safe, single-cable run, the tool only calibrates bands at or below
800 MHz and rejects anything higher. The 900 MHz ISM, STL, and DECT bands are
out of scope here; calibrate those separately if you need them.

## Command Line Options

| Flag | Default | Description |
|------|---------|-------------|
| `-tinysa` | `/dev/tty.usbmodem4001` | tinySA serial port |
| `-pluto` | `https://192.168.2.1` | Pluto maia-httpd URL |
| `-output` | `calibration.yaml` | YAML output (paste into `config.yaml`) |
| `-json` | `calibration.json` | JSON output (iOS client handoff) |
| `-serial` | *(none)* | Physical unit tag; redirects output to `calibrations/<serial>/` |
| `-outdir` | `calibrations` | Parent dir for per-unit folders (used with `-serial`) |
| `-level` | `-28.0` | tinySA output level in dBm (use whole numbers) |
| `-pad` | `0.0` | Inline attenuator in dB; recorded reference is `level - pad` |
| `-gain` | `30.0` | Pluto RX gain during calibration |
| `-band` | *(low-output band set)* | Band to sweep as `start:stop:step[:name]` in MHz; repeatable. Must be ≤ 800 MHz. |

### Bands

Pass `-band start:stop:step[:name]` once per band (MHz). Steps tune sampling
density and don't have to match your scan resolution. Any band that stops above
800 MHz is rejected (see scope note above). With no `-band` flag the tool sweeps
the default set, the ≤ 800 MHz subset of `Band.defaultBands` in
`spectrum-ios/SpectrumScanner/Models/Models.swift`:

| Band | Range (MHz) | Step |
|------|-------------|------|
| VHF | 174 – 216 | 6 |
| Business Radio | 450 – 470 | 5 |
| UHF | 470 – 636 | 6 |

Keep these ranges in sync with the iOS `defaultBands` list if it changes.

### Attenuator pad

The tool commands the tinySA to `-level` and assumes that power reaches the
Pluto. If you put a physical attenuator inline, pass its value via `-pad` so the
recorded `reference_dbm` reflects the true power at the Pluto (`level - pad`).
You cannot compensate by raising `-level` past the tinySA's max output, so the
pad is subtracted from the recorded reference instead.

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

## Comparing multiple units (is one default calibration safe?)

To decide whether a single baked-in default calibration is good enough — or
whether each Pluto needs its own — calibrate every unit with a `-serial` tag,
then run the comparison script.

maia-httpd doesn't expose the Pluto's hardware serial, so `-serial` is an
operator-supplied tag: use the sticker serial, `PlutoA`/`PlutoB`, or any label
that tells the units apart.

```bash
# 1. Calibrate each unit, tagged. Output lands in calibrations/<serial>/.
#    Keep -gain identical across units so the curves are comparable.
./calibrate -serial PlutoA          # -> calibrations/PlutoA/calibration.{json,yaml}
./calibrate -serial PlutoB          # -> calibrations/PlutoB/calibration.{json,yaml}

# 2. Compare. Globs calibrations/*/calibration_standalone.json by default.
python3 compare_calibrations.py                       # verdict at +/-1.0 dB
python3 compare_calibrations.py --tol 1.5             # looser tolerance
python3 compare_calibrations.py --emit-default default_calibration.json

# The plot needs matplotlib; uv pulls it in ephemerally without installing it:
uv run --with matplotlib python compare_calibrations.py --plot compare.png
```

The script computes each unit's **correction curve**
(`correction = reference_dbm − measured_dbm`, the dB the scanner adds), aligns
them on a common frequency grid using the same clamped linear interpolation the
scanner uses, and reports:

- the correction each unit wants per frequency and the **spread** between units,
- a proposed shared **default** (the per-frequency mean across units),
- the **worst-case error** if that default were shipped to every unit, and
- a **verdict** against the tolerance: if the worst unit lands within `±tol` dB
  of the mean, one shared default is safe; otherwise it names the units that
  need their own calibration.

`--emit-default` writes the mean curve as a `calibration.json` you can drop into
`config.yaml` (or ship as the baked-in default). The correction curve is roughly
gain-independent in the linear window, but the compression knee is not — the
script warns if the runs used different `-gain`, so keep gain matched.

Only the numeric report needs the standard library; `--plot` is optional.

## Output Format

The tool writes two files with the same data:

- **`calibration.yaml`** (`-output`) — paste into `config.yaml`
- **`calibration.json`** (`-json`) — for the iOS client; the field layout matches
  `models.Calibration`, so it is identical to what the scanner's REST endpoint
  serves

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

```json
{
  "reference_dbm": -28,
  "rx_gain": 30,
  "timestamp": "2024-01-23T20:45:19.137612-05:00",
  "points": [
    { "frequency_mhz": 470, "measured_dbm": -27.5 },
    { "frequency_mhz": 480, "measured_dbm": -27.8 }
  ]
}
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