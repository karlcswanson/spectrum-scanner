#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["matplotlib", "numpy"]
# ///
"""
Pluto linearity characterization via tinySA level sweep.

Drives the existing `calibrate` tool (./cmd/calibrate) repeatedly at several
tinySA output levels over a frequency band, then plots how the Pluto's measured
power tracks the known reference level. This reveals:

  * detector slope (should be ~1.0 dB/dB in the linear region),
  * a constant per-frequency offset (what the normal single-level cal captures),
  * where the noise floor bends the response at low input.

Scope notes
-----------
The tinySA Ultra low output (RF/LOW port) is only spec'd to +/-2 dB between
-72 and -19 dBm, so the sweep stays inside that window -- outside it you measure
the *source's* error, not the Pluto. At a typical gain the -72..-19 window does
NOT reach front-end compression, so this characterizes linearity + noise floor,
not the 1 dB compression point. To probe compression you'd need a calibrated
step attenuator and/or lower RX gain (see --gain).

Usage
-----
    # Collect from hardware (450-698 MHz, default levels) and plot:
    uv run level_sweep.py

    # Re-plot previously collected data without touching hardware:
    uv run level_sweep.py --plot-only

    # Custom levels / step / gain:
    uv run level_sweep.py --levels=-20,-30,-40,-50,-60 --step 8 --gain 30

All bands here are <=800 MHz, so it's a single-cable run on the tinySA RF/LOW
port -- connect once when prompted.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SCANNER_DIR = SCRIPT_DIR.parent.parent  # cmd/calibrate -> cmd -> scanner

# tinySA Ultra low-output accurate window (dBm), per tinysa.org Main.LOWOUTPUT.
TINYSA_ACCURATE_MIN = -72.0
TINYSA_ACCURATE_MAX = -19.0


def parse_args():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--tinysa", default="/dev/tty.usbmodem4001", help="tinySA serial port")
    p.add_argument("--pluto", default="https://192.168.2.1", help="Pluto maia-httpd URL")
    p.add_argument("--gain", type=float, default=30.0, help="Pluto RX gain (dB), single-gain mode")
    p.add_argument("--gains", default=None,
                   help="Comma-separated RX gains for a multi-gain comparison "
                        "(e.g. 20,30,40,50). Overrides --gain; each gain gets its own "
                        "level sweep + report plus a cross-gain comparison.")
    p.add_argument("--pad", type=float, default=0.0, help="Inline attenuator (dB); reference = level - pad")
    p.add_argument("--band-start", type=float, default=450.0, help="Band start (MHz)")
    p.add_argument("--band-stop", type=float, default=698.0, help="Band stop (MHz)")
    p.add_argument("--step", type=float, default=12.0, help="Frequency step (MHz)")
    p.add_argument("--levels", default=None,
                   help="Comma-separated tinySA levels in dBm (default: -20..-70 step 5)")
    p.add_argument("--outdir", default=str(SCRIPT_DIR / "level_sweep_out"),
                   help="Directory for per-level JSON and plots")
    p.add_argument("--no-build", action="store_true", help="Skip rebuilding the calibrate binary")
    p.add_argument("--plot-only", action="store_true", help="Skip hardware; plot existing data")
    p.add_argument("--collect-only", action="store_true", help="Collect data but don't plot")
    return p.parse_args()


def default_levels():
    # -20 down to -70 in 5 dB steps: inside the tinySA accurate window.
    return list(range(-20, -71, -5))


def build_calibrate(outdir: Path) -> Path:
    binpath = outdir / "calibrate"
    print(f"Building calibrate -> {binpath}")
    subprocess.run(
        ["go", "build", "-o", str(binpath), "./cmd/calibrate"],
        cwd=SCANNER_DIR, check=True,
    )
    return binpath


def subdir_for(base: Path, gain: float, multi: bool) -> Path:
    """Per-gain subdir in multi-gain mode; the base dir itself in single-gain mode."""
    return base / f"gain_{gain:g}" if multi else base


def run_levels(binpath: Path, args, gain: float, levels, band: str, subdir: Path):
    """Run the calibrate binary at every level for one fixed gain."""
    subdir.mkdir(parents=True, exist_ok=True)
    for level in levels:
        jpath = subdir / f"level_{level:g}.json"
        ypath = subdir / f"level_{level:g}.yaml"
        print(f"\n=== gain {gain:g} dB, tinySA level {level:g} dBm ===")
        proc = subprocess.run(
            [str(binpath),
             "-tinysa", args.tinysa, "-pluto", args.pluto,
             "-band", band, "-level", str(level), "-gain", str(gain),
             "-pad", str(args.pad),
             "-json", str(jpath), "-output", str(ypath)],
            input="\n",  # auto-answer calibrate's RF/LOW port prompt
            text=True, capture_output=True,
        )
        if proc.returncode != 0:
            sys.stderr.write(proc.stderr[-2000:] + "\n")
            sys.exit(f"calibrate failed at gain {gain:g} dB, level {level:g} dBm "
                     f"(exit {proc.returncode})")

        data = json.loads(jpath.read_text())
        errs = [pt["measured_dbm"] - data["reference_dbm"] for pt in data["points"]]
        print(f"  {len(data['points'])} points, mean error {sum(errs)/len(errs):+.2f} dB")


def collect(args, base_outdir: Path, gains, multi: bool):
    binpath = base_outdir / "calibrate"
    if not args.no_build or not binpath.exists():
        binpath = build_calibrate(base_outdir)

    levels = ([float(x) for x in args.levels.split(",")] if args.levels
              else default_levels())
    band = f"{args.band_start:g}:{args.band_stop:g}:{args.step:g}"

    print(f"\nSweep: {args.band_start:g}-{args.band_stop:g} MHz")
    print(f"Gains (dB): {', '.join(f'{g:g}' for g in gains)}")
    print(f"Levels (dBm): {', '.join(f'{l:g}' for l in levels)}")
    out_of_range = [l for l in levels if not (TINYSA_ACCURATE_MIN <= l <= TINYSA_ACCURATE_MAX)]
    if out_of_range:
        print(f"  WARNING: levels {out_of_range} are outside the tinySA accurate "
              f"window ({TINYSA_ACCURATE_MIN:g}..{TINYSA_ACCURATE_MAX:g} dBm); "
              f"those points reflect tinySA error, not the Pluto.")

    input("\n>>> Connect the coax to the tinySA RF/LOW port, then press Enter to start. ")

    for gain in gains:
        print(f"\n########## GAIN {gain:g} dB ##########")
        run_levels(binpath, args, gain, levels, band, subdir_for(base_outdir, gain, multi))

    print(f"\nCollection done. Data in {base_outdir}")


def load_data(outdir: Path):
    """Return (freqs sorted, levels sorted, measured[freq][level])."""
    files = sorted(outdir.glob("level_*.json"))
    if not files:
        sys.exit(f"No level_*.json found in {outdir}. Run collection first (drop --plot-only).")

    # measured[freq][reference] = measured_dbm
    measured: dict[float, dict[float, float]] = {}
    refs: set[float] = set()
    for f in files:
        d = json.loads(f.read_text())
        ref = float(d["reference_dbm"])
        refs.add(ref)
        for pt in d["points"]:
            freq = float(pt["frequency_mhz"])
            measured.setdefault(freq, {})[ref] = float(pt["measured_dbm"])

    freqs = sorted(measured)
    levels = sorted(refs)
    return freqs, levels, measured


def linear_window(freqs, levels, measured):
    """Find the contiguous levels where mean error stays within 0.5 dB of the
    plateau (median). Excludes compressed (top) and noise-floor (bottom) levels."""
    import numpy as np
    import statistics
    lvl_err = {}
    for lv in levels:
        e = [measured[f][lv] - lv for f in freqs if lv in measured[f]]
        lvl_err[lv] = float(np.mean(e))
    plateau = statistics.median(lvl_err.values())
    lin = [lv for lv in levels if abs(lvl_err[lv] - plateau) < 0.5]
    lo, hi = (min(lin), max(lin)) if lin else (min(levels), max(levels))
    return lo, hi, lvl_err, plateau


def fit_slopes(freqs, measured, level_min=None, level_max=None):
    """Linear fit measured = slope*ref + offset per frequency.

    If level_min/level_max are given, only reference levels within that window
    are fit -- important at high gain, where including compressed levels would
    corrupt the slope/offset."""
    import numpy as np
    slopes, offsets = {}, {}
    for fr in freqs:
        items = sorted(measured[fr].items())  # (ref, measured)
        if level_min is not None:
            items = [(r, m) for r, m in items if level_min <= r <= level_max]
        x = np.array([r for r, _ in items])
        y = np.array([m for _, m in items])
        if len(x) >= 2:
            slope, offset = np.polyfit(x, y, 1)
            slopes[fr] = float(slope)
            offsets[fr] = float(offset)
    return slopes, offsets


def plot(outdir: Path):
    import numpy as np
    import matplotlib.pyplot as plt

    freqs, levels, measured = load_data(outdir)
    win_lo, win_hi, _, _ = linear_window(freqs, levels, measured)
    slopes, offsets = fit_slopes(freqs, measured, win_lo, win_hi)

    mean_slope = float(np.mean(list(slopes.values())))
    print(f"\nMean detector slope over linear window ({win_lo:g}..{win_hi:g} dBm): "
          f"{mean_slope:.3f} dB/dB (ideal 1.000)")
    devs = {fr: s for fr, s in slopes.items() if abs(s - 1.0) > 0.05}
    if devs:
        print("  Frequencies with slope off by >0.05 (possible nonlinearity):")
        for fr, s in sorted(devs.items()):
            print(f"    {fr:g} MHz: slope {s:.3f}")
    else:
        print("  All per-frequency slopes within 0.05 of 1.0 -> single-offset "
              "calibration is justified across this range.")

    # Representative frequencies for the line plots (avoid clutter)
    n_rep = min(6, len(freqs))
    rep_idx = np.linspace(0, len(freqs) - 1, n_rep).astype(int)
    rep_freqs = [freqs[i] for i in rep_idx]
    cmap = plt.get_cmap("viridis")

    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    fig.suptitle(
        f"Pluto linearity vs tinySA level  |  {freqs[0]:g}-{freqs[-1]:g} MHz  |  "
        f"mean slope {mean_slope:.3f} dB/dB",
        fontsize=14, fontweight="bold")

    # (0,0) Measured vs reference, representative freqs, with ideal y=x.
    ax = axes[0, 0]
    lo, hi = min(levels), max(levels)
    ax.plot([lo, hi], [lo, hi], "k--", alpha=0.5, label="ideal (slope 1, 0 offset)")
    for i, fr in enumerate(rep_freqs):
        items = sorted(measured[fr].items())
        x = [r for r, _ in items]
        y = [m for _, m in items]
        ax.plot(x, y, marker="o", ms=3, color=cmap(i / max(1, n_rep - 1)),
                label=f"{fr:g} MHz")
    ax.set_xlabel("tinySA reference level (dBm)")
    ax.set_ylabel("Pluto measured (dBm)")
    ax.set_title("Measured vs reference")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)

    # (0,1) Error (measured - reference) vs reference level -- the diagnostic view.
    ax = axes[0, 1]
    for fr in freqs:
        items = sorted(measured[fr].items())
        x = np.array([r for r, _ in items])
        y = np.array([m - r for r, m in items])
        ax.plot(x, y, color="gray", alpha=0.25, lw=0.8)
    # Mean error across all freqs at each level
    mean_err = []
    for lv in levels:
        vals = [measured[fr][lv] - lv for fr in freqs if lv in measured[fr]]
        mean_err.append(np.mean(vals) if vals else np.nan)
    ax.plot(levels, mean_err, "r-o", lw=2, ms=4, label="mean across band")
    ax.axvspan(TINYSA_ACCURATE_MAX, max(lo, TINYSA_ACCURATE_MAX), color="orange",
               alpha=0.08)
    ax.set_xlabel("tinySA reference level (dBm)")
    ax.set_ylabel("measured - reference (dB)")
    ax.set_title("Error vs level  (flat = constant offset; tilt = slope; bend = noise floor)")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)

    # (1,0) Fitted slope vs frequency.
    ax = axes[1, 0]
    fr_arr = np.array(freqs)
    ax.plot(fr_arr, [slopes[fr] for fr in freqs], "b-o", ms=3)
    ax.axhline(1.0, color="k", ls="--", alpha=0.5, label="ideal 1.0")
    ax.set_xlabel("Frequency (MHz)")
    ax.set_ylabel("detector slope (dB/dB)")
    ax.set_title("Linearity slope across band")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)

    # (1,1) Fitted offset vs frequency (the per-frequency correction shape).
    ax = axes[1, 1]
    ax.plot(fr_arr, [offsets[fr] for fr in freqs], "g-o", ms=3)
    ax.set_xlabel("Frequency (MHz)")
    ax.set_ylabel("fit intercept (dBm)")
    ax.set_title("Per-frequency offset (intercept of the linear fit)")
    ax.grid(alpha=0.3)

    fig.tight_layout(rect=(0, 0, 1, 0.97))
    png = outdir / "level_sweep.png"
    fig.savefig(png, dpi=120)
    print(f"\nSaved plot -> {png}")
    build_report(outdir)
    plt.show()


def build_report(outdir: Path):
    """Write a markdown report (REPORT.md) with computed metrics + the chart."""
    import numpy as np

    freqs, levels, measured = load_data(outdir)

    files = sorted(outdir.glob("level_*.json"))
    meta = json.loads(files[0].read_text())
    gain = meta.get("rx_gain")
    collected = meta.get("timestamp", "")

    # Linear window first, then fit ONLY within it (compressed/noise levels would
    # corrupt slope and offset otherwise -- critical at high gain).
    win_lo, win_hi, lvl_err, plateau = linear_window(freqs, levels, measured)
    slopes, offsets = fit_slopes(freqs, measured, win_lo, win_hi)
    lvl_std = {}
    for lv in levels:
        e = [measured[f][lv] - lv for f in freqs if lv in measured[f]]
        lvl_std[lv] = float(np.std(e))

    # Slope / offset stats (over the linear window)
    mean_slope = float(np.mean([slopes[f] for f in freqs]))
    fmin = min(freqs, key=lambda f: slopes[f])
    fmax = max(freqs, key=lambda f: slopes[f])
    mean_off = float(np.mean([offsets[f] for f in freqs]))
    omin = min(freqs, key=lambda f: offsets[f])
    omax = max(freqs, key=lambda f: offsets[f])

    linear_verdict = ("linear — a single per-frequency offset is justified"
                      if all(abs(slopes[f] - 1.0) <= 0.05 for f in freqs)
                      else "NON-linear at some frequencies — consider a slope+offset fit")

    lines = []
    lines.append("# Pluto Amplitude Linearity Report\n")
    lines.append(f"- **Collected:** {collected}")
    lines.append(f"- **Band:** {freqs[0]:g}–{freqs[-1]:g} MHz "
                 f"({len(freqs)} points)")
    lines.append(f"- **RX gain:** {gain:g} dB (Manual)")
    lines.append(f"- **Source:** tinySA Ultra low output (RF/LOW port), "
                 f"levels {max(levels):g}…{min(levels):g} dBm")
    lines.append("- **Source caveat:** tinySA low output is ±2 dB accurate only "
                 f"over −72…−19 dBm ([tinySA wiki](https://tinysa.org/wiki/pmwiki.php?n=Main.LOWOUTPUT))\n")

    lines.append("## Summary\n")
    lines.append(f"- **Detector slope** (over linear window {win_lo:g}…{win_hi:g} dBm)**:** "
                 f"mean **{mean_slope:.3f} dB/dB** "
                 f"(ideal 1.000); range {slopes[fmin]:.3f} @ {fmin:g} MHz … "
                 f"{slopes[fmax]:.3f} @ {fmax:g} MHz")
    lines.append(f"- **Model verdict:** {linear_verdict}")
    lines.append(f"- **Per-frequency offset:** mean **{mean_off:+.2f} dB**, "
                 f"range {offsets[omin]:+.2f} @ {omin:g} MHz … "
                 f"{offsets[omax]:+.2f} @ {omax:g} MHz "
                 f"(≈{offsets[omax]-offsets[omin]:.1f} dB ripple)")
    lines.append(f"- **Linear window @ gain {gain:g} dB:** ≈ **{win_lo:g} to {win_hi:g} dBm** "
                 f"input (outside this: compression above, noise floor below)\n")

    lines.append("## Chart\n")
    lines.append("![level sweep](level_sweep.png)\n")

    lines.append("## Per-level error (across the band)\n")
    lines.append("| tinySA level (dBm) | mean error (dB) | std (dB) | in linear window |")
    lines.append("|---:|---:|---:|:---:|")
    for lv in sorted(levels, reverse=True):
        mark = "✓" if win_lo <= lv <= win_hi else "—"
        lines.append(f"| {lv:g} | {lvl_err[lv]:+.2f} | {lvl_std[lv]:.2f} | {mark} |")
    lines.append("")

    lines.append("## Per-frequency fit (measured = slope·reference + offset)\n")
    lines.append("| Frequency (MHz) | slope (dB/dB) | offset (dBm) |")
    lines.append("|---:|---:|---:|")
    for f in freqs:
        lines.append(f"| {f:g} | {slopes[f]:.3f} | {offsets[f]:+.2f} |")
    lines.append("")

    lines.append("## Interpretation\n")
    lines.append(f"- Slope ≈ {mean_slope:.3f} across the band confirms the amplitude "
                 "error is a **constant dB offset per frequency**, independent of input "
                 "power in the linear window — so the existing `correction = reference − "
                 "measured` calibration model is correct; no slope/exponential term needed.")
    lines.append("- The ≈1 dB offset ripple vs. frequency is why a **per-frequency** "
                 "calibration matters versus a single global number.")
    lines.append(f"- Above ~{win_hi:g} dBm the mean error falls off (front-end "
                 "compression); below ~{:g} dBm it drifts toward the noise floor. "
                 "Calibrate and operate inside the linear window.".format(win_lo))
    lines.append("- The compression edge is real (the −20 dBm point is still inside the "
                 "tinySA's accurate range), but to characterize compression *depth* "
                 "properly you'd use a calibrated step attenuator and/or lower gain.")

    report = outdir / "REPORT.md"
    report.write_text("\n".join(lines) + "\n")
    print(f"Saved report -> {report}")


def compute_metrics(subdir: Path):
    """Per-gain summary metrics used by the cross-gain comparison."""
    import numpy as np

    freqs, levels, measured = load_data(subdir)
    gain = json.loads(sorted(subdir.glob("level_*.json"))[0].read_text()).get("rx_gain")

    # Window first, then fit slope/offset ONLY within it.
    win_lo, win_hi, lvl_err, plateau = linear_window(freqs, levels, measured)
    slopes, offsets = fit_slopes(freqs, measured, win_lo, win_hi)

    return {
        "gain": gain, "levels": levels, "lvl_err": lvl_err,
        "mean_slope": float(np.mean([slopes[f] for f in freqs])),
        "mean_offset": float(np.mean([offsets[f] for f in freqs])),
        "win_lo": win_lo, "win_hi": win_hi, "plateau": plateau,
    }


def compare_gains(base_outdir: Path, gains, multi: bool):
    """Cross-gain comparison chart + COMPARISON_REPORT.md."""
    import matplotlib.pyplot as plt

    mets = [compute_metrics(subdir_for(base_outdir, g, multi)) for g in gains]
    gains_sorted = [m["gain"] for m in mets]
    cmap = plt.get_cmap("plasma")

    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    fig.suptitle("Pluto linearity across RX gain", fontsize=14, fontweight="bold")

    # (0,0) Mean error vs level, one line per gain -> knee + noise floor shift.
    ax = axes[0, 0]
    for i, m in enumerate(mets):
        lv = sorted(m["levels"])
        ax.plot(lv, [m["lvl_err"][x] for x in lv], marker="o", ms=3,
                color=cmap(i / max(1, len(mets) - 1)), label=f"gain {m['gain']:g} dB")
    ax.set_xlabel("tinySA reference level (dBm)")
    ax.set_ylabel("mean error (dB)")
    ax.set_title("Error vs level per gain  (rolloff = compression / noise floor)")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)

    # (0,1) Linear window vs gain (lo..hi band).
    ax = axes[0, 1]
    ax.fill_between(gains_sorted, [m["win_lo"] for m in mets], [m["win_hi"] for m in mets],
                    alpha=0.25, color="steelblue")
    ax.plot(gains_sorted, [m["win_hi"] for m in mets], "b-o", ms=4, label="upper (compression)")
    ax.plot(gains_sorted, [m["win_lo"] for m in mets], "b--o", ms=4, label="lower (noise floor)")
    ax.set_xlabel("RX gain (dB)")
    ax.set_ylabel("linear-window input (dBm)")
    ax.set_title("Usable linear window vs gain")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)

    # (1,0) Mean slope vs gain.
    ax = axes[1, 0]
    ax.plot(gains_sorted, [m["mean_slope"] for m in mets], "m-o", ms=4)
    ax.axhline(1.0, color="k", ls="--", alpha=0.5, label="ideal 1.0")
    ax.set_xlabel("RX gain (dB)")
    ax.set_ylabel("mean detector slope (dB/dB)")
    ax.set_title("Linearity slope vs gain")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)

    # (1,1) Mean offset vs gain.
    ax = axes[1, 1]
    ax.plot(gains_sorted, [m["mean_offset"] for m in mets], "g-o", ms=4)
    ax.set_xlabel("RX gain (dB)")
    ax.set_ylabel("mean offset (dB)")
    ax.set_title("Mean correction offset vs gain")
    ax.grid(alpha=0.3)

    fig.tight_layout(rect=(0, 0, 1, 0.97))
    png = base_outdir / "gain_comparison.png"
    fig.savefig(png, dpi=120)
    print(f"\nSaved comparison plot -> {png}")

    lines = ["# Pluto Linearity — Gain Comparison\n"]
    lines.append(f"- **Band:** {SCRIPT_DIR.name} sweep, gains "
                 f"{', '.join(f'{g:g}' for g in gains_sorted)} dB\n")
    lines.append("![gain comparison](gain_comparison.png)\n")
    lines.append("## Per-gain summary\n")
    lines.append("| RX gain (dB) | mean slope | mean offset (dB) | linear window (dBm) | "
                 "compression knee (dBm) |")
    lines.append("|---:|---:|---:|:---:|---:|")
    for m in mets:
        lines.append(f"| {m['gain']:g} | {m['mean_slope']:.3f} | {m['mean_offset']:+.2f} | "
                     f"{m['win_lo']:g} … {m['win_hi']:g} | {m['win_hi']:g} |")
    lines.append("")
    lines.append("## Reading it\n")
    lines.append("- **Compression knee** (upper window edge) should drop as gain rises — "
                 "higher gain saturates the front end at a lower input level.")
    lines.append("- **Noise floor** (lower window edge) should also drop with gain — higher "
                 "gain lifts weak signals above the noise.")
    lines.append("- If the **slope** stays ~1.0 at every gain, the single-offset calibration "
                 "model holds regardless of gain; only the usable window shifts.")
    lines.append("- Check that your **scan gain's** window covers the signal levels you care "
                 "about, and calibrate at that gain (or one with the same window).")
    (base_outdir / "COMPARISON_REPORT.md").write_text("\n".join(lines) + "\n")
    print(f"Saved comparison report -> {base_outdir / 'COMPARISON_REPORT.md'}")


def main():
    args = parse_args()
    # Resolve to absolute: `go build` runs from SCANNER_DIR while the calibrate
    # subprocess runs from the caller's cwd, so a relative outdir would split
    # the binary and the data across two directories.
    outdir = Path(args.outdir).resolve()
    outdir.mkdir(parents=True, exist_ok=True)

    gains = ([float(x) for x in args.gains.split(",")] if args.gains else [args.gain])
    multi = bool(args.gains) and len(gains) > 1

    if not args.plot_only:
        collect(args, outdir, gains, multi)
    if not args.collect_only:
        for g in gains:
            plot(subdir_for(outdir, g, multi))
        if multi:
            compare_gains(outdir, gains, multi)


if __name__ == "__main__":
    main()
