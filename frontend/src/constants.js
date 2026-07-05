// Timeline and scrubber constants

// Default lookback window for scrubber (10 minutes in hours)
export const SCRUBBER_HOURS = 0.167

// Default lookback for full timeline display
export const TIMELINE_HOURS = 24

// Default frequency bands — mirrors common/bands.json (the canonical source,
// from iOS Band.defaultBands). Keep in sync with it. Used by the band editor's
// "Reset to defaults". Only UHF is enabled by default.
export const DEFAULT_BANDS = [
  { name: 'VHF', start_hz: 174000000, stop_hz: 216000000, enabled: false },
  { name: 'Business Radio', start_hz: 450000000, stop_hz: 470000000, enabled: false },
  { name: 'UHF', start_hz: 470000000, stop_hz: 636000000, enabled: true },
  { name: '900 MHz ISM', start_hz: 902000000, stop_hz: 928000000, enabled: false },
  { name: 'STL', start_hz: 944000000, stop_hz: 960000000, enabled: false },
  { name: 'DECT', start_hz: 1920000000, stop_hz: 1930000000, enabled: false },
  { name: 'WiFi 2.4', start_hz: 2400000000, stop_hz: 2500000000, enabled: false },
  { name: 'CBRS', start_hz: 3550000000, stop_hz: 3700000000, enabled: false },
  { name: 'WiFi 5', start_hz: 5150000000, stop_hz: 5850000000, enabled: false },
]
