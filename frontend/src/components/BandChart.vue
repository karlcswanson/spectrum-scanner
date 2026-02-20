<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useScannersStore } from '../stores/scanners'
import D3SpectrumChart from './D3SpectrumChart.vue'
import SpectrogramChart from './SpectrogramChart.vue'
import TimeScrubber from './TimeScrubber.vue'
import FrequencyTimePlot from './FrequencyTimePlot.vue'

const props = defineProps({
  scannerId: {
    type: String,
    required: true,
  },
  scannerName: {
    type: String,
    default: '',
  },
  band: {
    type: Object,
    required: true,
  },
  scan: {
    type: Object,
    default: null,
  },
  // For multi-scanner overlay mode
  additionalTraces: {
    type: Array,
    default: () => [],
  },
  height: {
    type: Number,
    default: 300,
  },
  showScanner: {
    type: Boolean,
    default: true,
  },
  // Enable historical playback
  showTimeline: {
    type: Boolean,
    default: false,
  },
  // Timeline lookback in hours (default 24, use 0.167 for 10 min)
  timelineHours: {
    type: Number,
    default: 24,
  },
  // Enable selection checkbox for overlay comparison
  selectable: {
    type: Boolean,
    default: false,
  },
  selected: {
    type: Boolean,
    default: false,
  },
})

const emit = defineEmits(['update:selected'])

const store = useScannersStore()
const chartRef = ref(null)
const spectrogramRef = ref(null)

// Responsive chart height — smaller on phone-sized screens
const responsiveHeight = computed(() => {
  if (typeof window !== 'undefined' && window.innerWidth < 500) {
    return Math.min(props.height, 200)
  }
  return props.height
})

// Trace display modes
const showCurrent = ref(true)
const showAverage = ref(false)
const showPeak = ref(false)

// Historical playback state
const isLive = ref(true)
const historicalScan = ref(null)

// Zoom range from line chart (shared with spectrogram)
const zoomRange = ref(null)

// Shared cursor frequency between line chart and spectrogram
const sharedCursorFreq = ref(null)
const cursorSource = ref(null) // 'line' or 'spectrogram' — prevents feedback loops

function handleLineCursorMove(freqHz) {
  cursorSource.value = 'line'
  sharedCursorFreq.value = freqHz
}

function handleSpectrogramCursorMove(freqHz) {
  cursorSource.value = 'spectrogram'
  sharedCursorFreq.value = freqHz
}

// Cursor freq to pass to each chart (null when that chart owns the cursor)
const cursorFreqForLine = computed(() => cursorSource.value === 'spectrogram' ? sharedCursorFreq.value : null)
const cursorFreqForSpectrogram = computed(() => cursorSource.value === 'line' ? sharedCursorFreq.value : null)

// Click spectrogram row → show that scan in line chart
function handleSpectrogramSelect({ timestamp, scan }) {
  isLive.value = false
  historicalScan.value = scan
}

// Highlight time for spectrogram (timestamp of currently displayed scan)
const highlightTime = computed(() => {
  if (isLive.value) return null
  const scan = historicalScan.value
  if (!scan?.timestamp) return null
  // Ensure it's a numeric timestamp
  return typeof scan.timestamp === 'number' ? scan.timestamp : new Date(scan.timestamp).getTime()
})

// Pinned frequencies for time-series
const pinnedFreqs = ref([])
const pinColorPalette = ['#ff8c00', '#ff00ff', '#00ff00', '#ff4444', '#00bfff', '#ffff00', '#ff69b4', '#7fff00']

function handleFreqPin({ freqHz, freqMHz }) {
  // Toggle: remove if already pinned (within 0.1% tolerance)
  const tolerance = (props.band.stop_hz - props.band.start_hz) * 0.001
  const existingIdx = pinnedFreqs.value.findIndex(p => Math.abs(p.freqHz - freqHz) < tolerance)
  if (existingIdx >= 0) {
    // Replace array ref so shallow watchers fire
    pinnedFreqs.value = pinnedFreqs.value.filter((_, i) => i !== existingIdx)
    return
  }
  const color = pinColorPalette[pinnedFreqs.value.length % pinColorPalette.length]
  // Replace array ref so shallow watchers fire
  pinnedFreqs.value = [...pinnedFreqs.value, { freqHz, freqMHz, color }]

  // Auto-open waterfall if closed so the time-series has data
  if (!showSpectrogram.value) {
    showSpectrogram.value = true
    // loadSpectrogramData() fires via the watch on showSpectrogram
  }
}

function handleRemoveFreq(pin) {
  // Replace array ref so shallow watchers fire
  pinnedFreqs.value = pinnedFreqs.value.filter(p => p !== pin)
}

// Spectrogram toggle + lazy-loaded data (not stored globally)
const showSpectrogram = ref(false)
const spectrogramData = ref([])
const spectrogramLoading = ref(false)

// Time range for the frequency time-series plot, derived from spectrogram data
const freqPlotTimeRange = computed(() => {
  const data = spectrogramData.value
  if (data.length < 2) return null
  return [data[0].timestamp, data[data.length - 1].timestamp]
})

// Get timeline from store (reactive - updates via MQTT)
const timeline = computed(() => {
  if (!props.showTimeline) return []
  return store.getTimeline(props.scannerId, props.band.name)
})

// Are we showing live data right now?
const showingLive = computed(() => {
  return isLive.value && props.scan && props.scan.power && props.scan.power.length > 0
})

// Current time being displayed (for scrubber positioning)
const currentDisplayTime = computed(() => {
  if (showingLive.value) {
    return null // Live mode - scrubber at "now"
  }
  if (historicalScan.value?.timestamp) {
    return new Date(historicalScan.value.timestamp)
  }
  return null
})

// Active scan - use historical if selected, otherwise live
const activeScan = computed(() => {
  // If user selected historical time, show historical scan
  if (!isLive.value && historicalScan.value) {
    return historicalScan.value
  }
  // Otherwise show live scan if available
  if (props.scan && props.scan.power && props.scan.power.length > 0) {
    return props.scan
  }
  // Fall back to historical if no live data
  return historicalScan.value
})

// Lazy-load spectrogram historical data (local, not in store)
async function loadSpectrogramData() {
  if (!showSpectrogram.value) return
  spectrogramLoading.value = true
  try {
    const rangeOpts = currentTimeRange.value
    let fetchOpts
    if (rangeOpts.start && rangeOpts.end) {
      fetchOpts = {
        start: rangeOpts.start,
        end: rangeOpts.end,
      }
    } else {
      fetchOpts = {
        hours: rangeOpts.hours || props.timelineHours,
      }
    }
    const scans = await store.fetchHistory(props.scannerId, props.band.name, fetchOpts)
    if (scans && scans.length > 0) {
      spectrogramData.value = scans.map(s => ({
        timestamp: new Date(s.timestamp).getTime(),
        scan: {
          hz_lo: s.hz_lo,
          hz_hi: s.hz_hi,
          step: s.step_hz,
          power: s.power,
          timestamp: s.timestamp,
        }
      })).sort((a, b) => a.timestamp - b.timestamp)
    } else {
      spectrogramData.value = []
    }
  } catch (err) {
    spectrogramData.value = []
  } finally {
    spectrogramLoading.value = false
  }
}

// Load when toggled on, clear when toggled off
watch(showSpectrogram, (open) => {
  if (open) {
    loadSpectrogramData()
  } else {
    spectrogramData.value = []
  }
})

function handleZoom(domain) {
  zoomRange.value = domain
}

// Format step size for display
function formatStep(stepHz) {
  if (!stepHz) return ''
  if (stepHz >= 1000) {
    return `${(stepHz / 1000).toFixed(1)} kHz`
  }
  return `${stepHz.toFixed(0)} Hz`
}

const scanInfo = computed(() => {
  const scan = activeScan.value
  if (!scan?.power) return '--'
  const power = scan.power
  const points = power.length
  const step = formatStep(scan.step)
  let minP = power[0], maxP = power[0]
  for (let i = 1; i < points; i++) {
    if (power[i] < minP) minP = power[i]
    if (power[i] > maxP) maxP = power[i]
  }
  return `${points} pts | ${step} | ${minP.toFixed(1)} to ${maxP.toFixed(1)} dBm`
})

const freqRange = computed(() => {
  const start = (props.band.start_hz / 1e6).toFixed(0)
  const stop = (props.band.stop_hz / 1e6).toFixed(0)
  return `${start}-${stop} MHz`
})

// Build traces array for D3 chart
// When viewing historical data, show BOTH live (dimmed) and historical (bright)
const traces = computed(() => {
  const result = []

  // If we have live scan data, always show it
  const hasLiveScan = props.scan && props.scan.power && props.scan.power.length > 0

  // Historical trace (yellow, when scrubbing)
  if (!isLive.value && historicalScan.value) {
    result.push({
      id: `${props.scannerId}-historical`,
      name: 'Historical',
      scan: historicalScan.value,
      color: '#fbbf24', // yellow
    })
  }

  // Live trace - show dimmed when viewing historical, bright when live
  if (hasLiveScan) {
    result.push({
      id: props.scannerId,
      name: isLive.value ? (props.scannerName || 'Live') : 'Live',
      scan: props.scan,
      color: isLive.value ? '#00d4ff' : '#00d4ff80', // dimmed cyan when viewing historical
    })
  } else if (isLive.value && historicalScan.value) {
    // Fallback: show historical as primary if no live data
    result.push({
      id: props.scannerId,
      name: props.scannerName || props.scannerId,
      scan: historicalScan.value,
      color: '#00d4ff',
    })
  }

  // Additional traces from other scanners
  props.additionalTraces.forEach((trace, idx) => {
    result.push({
      id: trace.scannerId || `additional-${idx}`,
      name: trace.scannerName || `Scanner ${idx + 2}`,
      scan: trace.scan,
      color: trace.color,
    })
  })

  return result
})

function exportCSV() {
  const scan = activeScan.value
  if (!scan) return

  // Generate CSV from the currently displayed scan
  let csv = 'Frequency (MHz),Power (dBm)\n'
  const startMHz = scan.hz_lo / 1e6
  const stepMHz = scan.step / 1e6

  for (let i = 0; i < scan.power.length; i++) {
    const freq = startMHz + (i * stepMHz)
    csv += `${freq.toFixed(6)},${scan.power[i].toFixed(2)}\n`
  }

  const blob = new Blob([csv], { type: 'text/csv' })
  const url = URL.createObjectURL(blob)

  const scannerName = props.scannerName || props.scannerId
  const timestamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19)
  const filename = `${scannerName.replace(/\s+/g, '-')}_${props.band.name.replace(/\s+/g, '-')}_${timestamp}.csv`

  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()

  URL.revokeObjectURL(url)
}

function resetPeakHold() {
  if (chartRef.value) {
    chartRef.value.resetAllPeaks()
  }
}

// Current time range (for refetching)
const currentTimeRange = ref({ hours: props.timelineHours })

// Timeline handlers
async function loadTimeline(options = null) {
  if (props.showTimeline) {
    const rangeOpts = options || currentTimeRange.value
    // Fetch initial timeline data - store handles MQTT updates after this
    await store.fetchTimeline(props.scannerId, props.band.name, rangeOpts)
    // Load decimated cache matching scrubber range (API auto-fills with rollup data)
    await store.loadDecimatedCache(props.scannerId, props.band.name, rangeOpts)
  }
}

// Handle time range change from scrubber
async function handleRangeChange(rangeOpts) {
  currentTimeRange.value = rangeOpts
  await loadTimeline(rangeOpts)
  // Reload spectrogram data for new range if open
  if (showSpectrogram.value) {
    loadSpectrogramData()
  }
}

// Preview handler (while dragging) - use decimated cache
function handleTimePreview(time) {
  isLive.value = false
  const scan = store.findScanInDecimatedCache(props.scannerId, props.band.name, time)
  if (scan) {
    historicalScan.value = {
      hz_lo: scan.hz_lo,
      hz_hi: scan.hz_hi,
      step: scan.step,
      power: scan.power,
      timestamp: scan.timestamp,
    }
  }
}

// Select handler (on release) - fetch full resolution
async function handleTimeSelect(time) {
  isLive.value = false
  // Fetch full resolution scan from API
  const scan = await store.fetchScanAtTime(props.scannerId, time, props.band.name)
  if (scan) {
    historicalScan.value = {
      hz_lo: scan.hz_lo,
      hz_hi: scan.hz_hi,
      step: scan.step_hz,
      power: scan.power,
      timestamp: scan.timestamp,
    }
  }
}

function handleLive() {
  isLive.value = true
  historicalScan.value = null
  // Spectrogram handles mode switch via isLive watcher (pre-fills from historical)
}

// Check if we have valid live scan data
function hasLiveScan() {
  return props.scan && props.scan.power && props.scan.power.length > 0
}

// Load the most recent historical scan (as fallback, stays in live mode)
function loadLatestHistorical() {
  const cache = store.getScanCache(props.scannerId, props.band.name)
  if (cache.length > 0) {
    // Get the most recent scan from cache
    const latest = cache[cache.length - 1]
    historicalScan.value = {
      hz_lo: latest.scan.hz_lo,
      hz_hi: latest.scan.hz_hi,
      step: latest.scan.step,
      power: latest.scan.power,
      timestamp: latest.scan.timestamp,
    }
    // Keep isLive = true so we switch to live data when it arrives
  }
}

// Load timeline on mount if enabled, and fetch latest scan if no live data
onMounted(async () => {
  await loadTimeline()

  // If no live scan and we have cached data, load the most recent scan
  if (!hasLiveScan()) {
    loadLatestHistorical()
  }
})

// Reload timeline when band changes
watch(() => props.band.name, async () => {
  await loadTimeline()
  // Reload spectrogram data if open
  if (showSpectrogram.value) {
    loadSpectrogramData()
  }
  // Load latest historical if no live scan
  if (!hasLiveScan()) {
    loadLatestHistorical()
  }
})

// No need for periodic refresh - MQTT handles timeline updates
</script>

<template>
  <div
    class="bg-gray-800 rounded-lg p-2 sm:p-4 transition-all"
    :class="selected ? 'ring-2 ring-cyan-500' : ''"
  >
    <div class="flex flex-wrap items-start justify-between gap-x-3 gap-y-1 mb-3">
      <div class="flex items-start gap-2 sm:gap-3 min-w-0">
        <!-- Selection checkbox -->
        <label v-if="selectable" class="flex items-center mt-1 cursor-pointer">
          <input
            type="checkbox"
            :checked="selected"
            @change="emit('update:selected', !selected)"
            class="w-4 h-4 accent-cyan-400 cursor-pointer"
          />
        </label>

        <div class="min-w-0">
          <h2 class="text-base sm:text-lg font-semibold text-cyan-400">
            {{ band.name }}
            <span class="text-gray-500 font-normal text-xs sm:text-sm ml-1 sm:ml-2">
              ({{ freqRange }})
            </span>
            <span v-if="!showingLive && activeScan" class="text-yellow-400 text-xs ml-1 sm:ml-2">
              Historical
            </span>
          </h2>
          <p class="text-xs text-gray-500 truncate">
            <span v-if="showScanner && scannerName" class="mr-3">{{ scannerName }}</span>
            {{ scanInfo }}
          </p>
        </div>
      </div>

      <div class="flex items-center gap-2 flex-wrap ml-auto">
        <!-- Trace mode toggles -->
        <div class="flex items-center gap-2 text-xs">
          <label class="flex items-center gap-1 cursor-pointer">
            <input type="checkbox" v-model="showCurrent" class="w-3 h-3 accent-cyan-400" />
            <span class="text-gray-400">Current</span>
          </label>
          <label class="flex items-center gap-1 cursor-pointer">
            <input type="checkbox" v-model="showAverage" class="w-3 h-3 accent-yellow-400" />
            <span class="text-gray-400">Avg</span>
          </label>
          <label class="flex items-center gap-1 cursor-pointer">
            <input type="checkbox" v-model="showPeak" class="w-3 h-3 accent-red-400" />
            <span class="text-gray-400">Peak</span>
          </label>
          <button
            v-if="showPeak"
            @click="resetPeakHold"
            class="px-2 py-0.5 rounded text-xs bg-gray-700 hover:bg-gray-600 text-gray-300"
          >
            Reset
          </button>
        </div>

        <button
          @click="exportCSV"
          :disabled="!activeScan"
          class="px-3 py-1.5 rounded text-xs font-semibold transition-colors"
          :class="activeScan
            ? 'bg-green-500 hover:bg-green-600 text-black'
            : 'bg-gray-600 text-gray-400 cursor-not-allowed'"
        >
          Export
        </button>
      </div>
    </div>

    <D3SpectrumChart
      ref="chartRef"
      :traces="traces"
      :band="band"
      :height="responsiveHeight"
      :show-current="showCurrent"
      :show-average="showAverage"
      :show-peak="showPeak"
      :cursor-freq="cursorFreqForLine"
      :pinned-freqs="pinnedFreqs"
      @zoom="handleZoom"
      @cursor-move="handleLineCursorMove"
      @freq-pin="handleFreqPin"
    />

    <!-- Spectrogram toggle -->
    <div class="flex items-center mt-1">
      <button
        @click="showSpectrogram = !showSpectrogram"
        class="flex items-center gap-1 px-2 py-0.5 rounded text-xs transition-colors"
        :class="showSpectrogram
          ? 'bg-cyan-600/20 text-cyan-400 hover:bg-cyan-600/30'
          : 'bg-gray-700 text-gray-500 hover:bg-gray-600'"
      >
        <span class="text-[10px]">{{ showSpectrogram ? '&#9660;' : '&#9654;' }}</span>
        Waterfall
      </button>
    </div>

    <div v-if="showSpectrogram" class="relative mt-1">
      <!-- Loading overlay -->
      <div
        v-if="spectrogramLoading"
        class="absolute inset-0 z-10 flex items-center justify-center bg-gray-900/60 rounded"
      >
        <svg class="animate-spin h-6 w-6 text-cyan-400" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
        </svg>
      </div>
      <SpectrogramChart
      ref="spectrogramRef"
      :band="band"
      :height="200"
      :scan="scan"
      :historical-scans="spectrogramData"
      :is-live="isLive"
      :visible-range="zoomRange"
      :cursor-freq="cursorFreqForSpectrogram"
      :highlight-time="highlightTime"
      :pinned-freqs="pinnedFreqs"
      @cursor-move="handleSpectrogramCursorMove"
      @select="handleSpectrogramSelect"
      @freq-pin="handleFreqPin"
    />
    </div>

    <!-- Frequency time-series plot for pinned frequencies -->
    <FrequencyTimePlot
      v-if="pinnedFreqs.length > 0"
      :pinned-freqs="pinnedFreqs"
      :scans="spectrogramData"
      :time-range="freqPlotTimeRange"
      :live-scan="scan"
      :is-live="isLive"
      class="mt-1"
      @remove-freq="handleRemoveFreq"
    />

    <!-- Time scrubber for historical playback -->
    <TimeScrubber
      v-if="showTimeline"
      :scanner-id="scannerId"
      :band-name="band.name"
      :timeline="timeline"
      :max-hours="timelineHours"
      :height="50"
      :showing-live="showingLive"
      :current-time="currentDisplayTime"
      :last-scan-time="scan?._receivedAt"
      :tick="store.tick"
      class="mt-3"
      @preview="handleTimePreview"
      @select="handleTimeSelect"
      @live="handleLive"
      @range-change="handleRangeChange"
    />
  </div>
</template>
