<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { useScannersStore } from '../stores/scanners'
import { SCRUBBER_HOURS } from '../constants'
import D3SpectrumChart from './D3SpectrumChart.vue'
import TimeScrubber from './TimeScrubber.vue'

const props = defineProps({
  // Frequency range for this chart (Hz)
  startHz: {
    type: Number,
    required: true,
  },
  stopHz: {
    type: Number,
    required: true,
  },
  // Optional label for this frequency range
  label: {
    type: String,
    default: '',
  },
  // Available scanners that can display on this chart
  availableScanners: {
    type: Array,
    default: () => [],
  },
  height: {
    type: Number,
    default: 350,
  },
  // Enable historical playback
  showTimeline: {
    type: Boolean,
    default: true,
  },
})

const store = useScannersStore()
const chartRef = ref(null)

// Trace display modes
const showCurrent = ref(true)
const showAverage = ref(false)
const showPeak = ref(false)

// Historical playback state
const isLive = ref(true)
const historicalScans = ref({}) // { 'scannerId:bandName': scan } - currently displayed

// Color palette for multiple scanners
const scannerColors = [
  '#00d4ff', // cyan
  '#ff6b6b', // red
  '#4ecdc4', // teal
  '#ffe66d', // yellow
  '#95e1d3', // mint
  '#f38181', // coral
  '#aa96da', // lavender
  '#fcbad3', // pink
]

// Get color for a scanner (consistent based on index in availableScanners)
function getScannerColor(idx) {
  return scannerColors[idx % scannerColors.length]
}

// Combine timelines from all selected scanners
// Cache the combined result and only rebuild when lengths change
const timelineCache = new Map()
let cachedTimeline = []
let cachedLengths = ''

function getTimestampMs(entry) {
  if (!timelineCache.has(entry.id)) {
    timelineCache.set(entry.id, new Date(entry.timestamp).getTime())
  }
  return timelineCache.get(entry.id)
}

const combinedTimeline = computed(() => {
  // Depend on tick to check periodically
  void store.tick

  // Build a signature of current timeline lengths
  const lengths = props.availableScanners
    .map(s => store.getTimeline(s.scannerId, s.bandName).length)
    .join(',')

  // Only rebuild if lengths changed
  if (lengths !== cachedLengths) {
    cachedLengths = lengths
    const allEntries = []
    for (const scanner of props.availableScanners) {
      const timeline = store.getTimeline(scanner.scannerId, scanner.bandName)
      allEntries.push(...timeline)
    }
    cachedTimeline = allEntries.sort((a, b) => getTimestampMs(a) - getTimestampMs(b))
  }

  return cachedTimeline
})

// Get the latest scan timestamp for triggering redraws
const latestScanTime = computed(() => {
  let latest = null
  for (const scanner of props.availableScanners) {
    const scan = store.bandScans[scanner.scannerId]?.[scanner.bandName]
    if (scan?._receivedAt && (!latest || scan._receivedAt > latest)) {
      latest = scan._receivedAt
    }
  }
  return latest
})

// Are we showing live data?
const showingLive = computed(() => {
  return isLive.value
})

// Current time being displayed (for scrubber positioning)
const currentDisplayTime = computed(() => {
  if (showingLive.value) {
    return null
  }
  // Return the earliest historical scan timestamp we have
  const times = Object.values(historicalScans.value)
    .filter(s => s?.timestamp)
    .map(s => new Date(s.timestamp))
  if (times.length > 0) {
    return new Date(Math.min(...times))
  }
  return null
})

// Build traces for the D3 chart from all available scanners
const traces = computed(() => {
  const result = []

  props.availableScanners.forEach((scanner, idx) => {
    const key = `${scanner.scannerId}:${scanner.bandName}`

    // Use historical scan if not live, otherwise use live scan
    let scan
    if (!isLive.value && historicalScans.value[key]) {
      scan = historicalScans.value[key]
    } else {
      scan = store.bandScans[scanner.scannerId]?.[scanner.bandName]
    }

    if (!scan?.power?.length) return

    result.push({
      id: `${scanner.scannerId}-${scanner.bandName}`,
      name: scanner.scannerName || scanner.scannerId,
      scan: scan,
      color: getScannerColor(idx),
    })
  })

  return result
})

// Frequency range display
const freqRange = computed(() => {
  const startMHz = (props.startHz / 1e6).toFixed(0)
  const stopMHz = (props.stopHz / 1e6).toFixed(0)
  return `${startMHz}-${stopMHz} MHz`
})

// Chart info
const chartInfo = computed(() => {
  const activeTraces = traces.value.length
  const totalScanners = props.availableScanners.length
  return `${activeTraces}/${totalScanners} scanners`
})

function resetPeakHold() {
  if (chartRef.value) {
    chartRef.value.resetAllPeaks()
  }
}

function exportCSV() {
  // Export all visible traces
  traces.value.forEach(trace => {
    const scan = trace.scan
    if (!scan) return

    let csv = 'Frequency (MHz),Power (dBm)\n'
    const startMHz = scan.hz_lo / 1e6
    const stepMHz = scan.step / 1e6

    for (let i = 0; i < scan.power.length; i++) {
      const freq = startMHz + (i * stepMHz)
      csv += `${freq.toFixed(6)},${scan.power[i].toFixed(2)}\n`
    }

    const blob = new Blob([csv], { type: 'text/csv' })
    const url = URL.createObjectURL(blob)

    const timestamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19)
    const filename = `${trace.name.replace(/\s+/g, '-')}_${timestamp}.csv`

    const a = document.createElement('a')
    a.href = url
    a.download = filename
    a.click()

    URL.revokeObjectURL(url)
  })
}

// Preview handler (while dragging) - use decimated cache for instant response
function handleTimePreview(time) {
  isLive.value = false

  const newScans = {}
  for (const scanner of props.availableScanners) {
    const key = `${scanner.scannerId}:${scanner.bandName}`
    const scan = store.findScanInDecimatedCache(scanner.scannerId, scanner.bandName, time)
    if (scan) {
      newScans[key] = scan
    }
  }
  historicalScans.value = newScans
}

// Select handler (on release) - fetch full resolution from API
async function handleTimeSelect(time) {
  isLive.value = false

  const newScans = {}
  const fetchPromises = props.availableScanners.map(async (scanner) => {
    const key = `${scanner.scannerId}:${scanner.bandName}`
    const scan = await store.fetchScanAtTime(scanner.scannerId, time, scanner.bandName)
    if (scan) {
      newScans[key] = {
        hz_lo: scan.hz_lo,
        hz_hi: scan.hz_hi,
        step: scan.step_hz,
        power: scan.power,
        timestamp: scan.timestamp,
      }
    }
  })

  await Promise.all(fetchPromises)
  historicalScans.value = newScans
}

function handleLive() {
  isLive.value = true
  historicalScans.value = {}
}

// Track which scanners we've loaded data for
const loadedScannerKeys = ref(new Set())

// Load timelines and decimated cache only for new scanners
watch(() => props.availableScanners, async (newScanners) => {
  if (!props.showTimeline) return

  for (const scanner of newScanners) {
    const key = `${scanner.scannerId}:${scanner.bandName}`
    if (!loadedScannerKeys.value.has(key)) {
      loadedScannerKeys.value.add(key)
      // Fetch initial timeline (MQTT will update it after this)
      store.fetchTimeline(scanner.scannerId, scanner.bandName, 24)
      // Load decimated cache for scrubbing
      store.loadDecimatedCache(scanner.scannerId, scanner.bandName, SCRUBBER_HOURS)
    }
  }
}, { immediate: true })
</script>

<template>
  <div class="bg-gray-800 rounded-lg p-4">
    <div class="flex justify-between items-start mb-3">
      <div>
        <h2 class="text-lg font-semibold text-cyan-400">
          {{ label || freqRange }}
          <span v-if="label" class="text-gray-500 font-normal text-sm ml-2">
            ({{ freqRange }})
          </span>
          <span v-if="!showingLive" class="text-yellow-400 text-xs ml-2">
            Historical
          </span>
        </h2>
        <p class="text-xs text-gray-500">{{ chartInfo }}</p>
      </div>

      <div class="flex items-center gap-3">
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
          :disabled="traces.length === 0"
          class="px-4 py-2 rounded text-sm font-semibold transition-colors"
          :class="traces.length > 0
            ? 'bg-green-500 hover:bg-green-600 text-black'
            : 'bg-gray-600 text-gray-400 cursor-not-allowed'"
        >
          Export CSV
        </button>
      </div>
    </div>

    <!-- Legend showing scanner colors -->
    <div v-if="traces.length > 1" class="flex flex-wrap gap-3 mb-3">
      <div
        v-for="(trace, idx) in traces"
        :key="trace.id"
        class="flex items-center gap-1.5 text-xs"
      >
        <span
          class="w-3 h-3 rounded-sm"
          :style="{ backgroundColor: trace.color }"
        ></span>
        <span class="text-gray-300">{{ trace.name }}</span>
      </div>
    </div>

    <D3SpectrumChart
      ref="chartRef"
      :traces="traces"
      :band="{ start_hz: startHz, stop_hz: stopHz }"
      :height="height"
      :show-current="showCurrent"
      :show-average="showAverage"
      :show-peak="showPeak"
    />

    <!-- Time scrubber for historical playback -->
    <TimeScrubber
      v-if="showTimeline && availableScanners.length > 0"
      :scanner-id="availableScanners[0]?.scannerId || ''"
      :timeline="combinedTimeline"
      :max-hours="SCRUBBER_HOURS"
      :height="50"
      :showing-live="showingLive"
      :current-time="currentDisplayTime"
      :last-scan-time="latestScanTime"
      :hide-markers="false"
      class="mt-3"
      @preview="handleTimePreview"
      @select="handleTimeSelect"
      @live="handleLive"
    />
  </div>
</template>
