// Spectrum export helpers — trace reduction, CSV formatting, and download.
//
// Formats are matched to the iOS export wizard so files interop with the same
// coordination tooling:
//   - CSV header:  "Frequency (MHz), Amplitude (dBm)"  (space after comma in the
//     header only; data rows are "%.6f,%.2f" with no space)
//   - one row per frequency bin; bin i center = hz_lo + i*step
//   - multiple bands concatenate into one file, ascending by start frequency
//   - Peak  = per-bin max across the scans in range
//   - Average = mean in the LINEAR power domain, back to dB, floored at -140 dBm
//     (NOT a naive dB mean)

// Truncate a set of power arrays to a common length (the shortest) so element-
// wise reduction never mixes mismatched bin grids. Scanners occasionally emit
// sweeps a few bins short; truncating keeps them rather than dropping data.
function toCommonGrid(arrays) {
  const nonEmpty = arrays.filter((a) => a && a.length)
  if (!nonEmpty.length) return []
  const n = Math.min(...nonEmpty.map((a) => a.length))
  return nonEmpty.map((a) => a.subarray ? a.subarray(0, n) : a.slice(0, n))
}

// Per-bin maximum across scans.
export function reducePeak(arrays) {
  const grid = toCommonGrid(arrays)
  if (!grid.length) return []
  const n = grid[0].length
  const out = new Array(n).fill(-Infinity)
  for (const a of grid) {
    for (let i = 0; i < n; i++) if (a[i] > out[i]) out[i] = a[i]
  }
  return out
}

// Per-bin average in the linear power domain, converted back to dB, floor -140.
export function reduceAverageLinear(arrays) {
  const grid = toCommonGrid(arrays)
  if (!grid.length) return []
  const n = grid[0].length
  const acc = new Array(n).fill(0)
  for (const a of grid) {
    for (let i = 0; i < n; i++) acc[i] += Math.pow(10, a[i] / 10)
  }
  const c = grid.length
  return acc.map((s) => {
    const m = s / c
    return m > 0 ? 10 * Math.log10(m) : -140
  })
}

// Reduce a band's scans to a single full-resolution trace. `scans` is an array
// of { hz_lo, step, power }. Returns { hz_lo, step, power } or null if empty.
// trace: 'live' uses the last scan; 'peak'/'average' reduce across all scans.
// Exports are always full-resolution — no decimation.
export function buildBandTrace(scans, trace) {
  if (!scans || !scans.length) return null
  const geom = scans[scans.length - 1] // newest defines geometry
  let power
  if (trace === 'peak') {
    power = reducePeak(scans.map((s) => s.power))
  } else if (trace === 'average') {
    power = reduceAverageLinear(scans.map((s) => s.power))
  } else {
    power = Array.from(geom.power)
  }
  if (!power.length) return null
  return { hz_lo: geom.hz_lo, step: geom.step, power }
}

// Build the CSV text from one or more band traces (each { hz_lo, step, power }),
// concatenated in the given order under a single header. Matches iOS exactly.
export function buildCSV(bandTraces) {
  let csv = 'Frequency (MHz), Amplitude (dBm)\n'
  for (const b of bandTraces) {
    if (!b) continue
    const startMHz = b.hz_lo / 1e6
    const stepMHz = b.step / 1e6
    for (let i = 0; i < b.power.length; i++) {
      const freq = startMHz + i * stepMHz
      csv += `${freq.toFixed(6)},${b.power[i].toFixed(2)}\n`
    }
  }
  return csv
}

// Two-digit zero-padded helper for filename timestamps.
function pad2(n) {
  return String(n).padStart(2, '0')
}

// Filename matching the iOS/Soundbase convention:
//   Scan_<loMHz>-<hiMHz>_<band|Nbands>_<yyyyMMdd-HHmmss>[_peak|_avg].csv
// `bands` is an array of { name, hz_lo, hz_hi } already sorted ascending.
export function exportFilename(bands, trace, date = new Date()) {
  const lo = Math.round(bands[0].hz_lo / 1e6)
  const hi = Math.round(bands[bands.length - 1].hz_hi / 1e6)
  const bandToken =
    bands.length === 1 ? bands[0].name.replace(/\s+/g, '_') : `${bands.length}bands`
  const ts =
    `${date.getFullYear()}${pad2(date.getMonth() + 1)}${pad2(date.getDate())}` +
    `-${pad2(date.getHours())}${pad2(date.getMinutes())}${pad2(date.getSeconds())}`
  const suffix = trace === 'peak' ? '_peak' : trace === 'average' ? '_avg' : ''
  return `Scan_${lo}-${hi}_${bandToken}_${ts}${suffix}.csv`
}

// Trigger a browser download of text content.
export function downloadText(filename, text, mime = 'text/csv') {
  const blob = new Blob([text], { type: mime })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}
