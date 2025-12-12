<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { useScannersStore } from '../stores/scanners'
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
const scanCache = ref({}) // { 'scannerId:bandName': [{ timestamp, scan }, ...] } - all loaded history
const cacheLoading = ref(false)

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
const combinedTimeline = computed(() => {
  const allEntries = []
  for (const scanner of props.availableScanners) {
    const timeline = store.getTimeline(scanner.scannerId, scanner.bandName)
    allEntries.push(...timeline)
  }
  // Sort by timestamp - parse once, not on every comparison
  return allEntries
    .map(t => ({ ...t, _ts: new Date(t.timestamp).getTime() }))
    .sort((a, b) => a._ts - b._ts)
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

// Timeline handlers
async function loadTimelines() {
  // Fetch timeline for each selected scanner/band
  for (const scanner of props.availableScanners) {
    await store.fetchTimeline(scanner.scannerId, scanner.bandName, 24)
  }
}

// Load all historical data for selected scanners into cache
async function loadScanCache() {
  cacheLoading.value = true
  const hours = 0.167 // 10 minutes - matches scrubber max-hours

  const loadPromises = props.availableScanners.map(async (scanner) => {
    const key = `${scanner.scannerId}:${scanner.bandName}`
    try {
      // Fetch all scans for this scanner/band in the time window
      const scans = await store.fetchHistory(scanner.scannerId, scanner.bandName, hours, 1000)
      if (scans && scans.length > 0) {
        // Store as sorted array with parsed timestamps for fast lookup
        scanCache.value[key] = scans.map(s => ({
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
        scanCache.value[key] = []
      }
    } catch (err) {
      console.error(`Error loading cache for ${scanner.scannerName}/${scanner.bandName}:`, err)
      scanCache.value[key] = []
    }
  })

  await Promise.all(loadPromises)
  scanCache.value = { ...scanCache.value }
  cacheLoading.value = false
  console.log('Scan cache loaded:', Object.keys(scanCache.value).map(k => `${k}: ${scanCache.value[k].length} scans`))
}

// Find closest scan in cache (binary search)
function findClosestInCache(key, targetTime) {
  const cache = scanCache.value[key]
  if (!cache || cache.length === 0) return null

  const targetMs = targetTime.getTime()

  // Binary search for closest
  let left = 0
  let right = cache.length - 1

  while (left < right) {
    const mid = Math.floor((left + right) / 2)
    if (cache[mid].timestamp < targetMs) {
      left = mid + 1
    } else {
      right = mid
    }
  }

  // Check left and left-1 to find closest
  const candidates = []
  if (left < cache.length) candidates.push(cache[left])
  if (left > 0) candidates.push(cache[left - 1])

  let closest = null
  let closestDiff = Infinity
  for (const c of candidates) {
    const diff = Math.abs(c.timestamp - targetMs)
    if (diff < closestDiff) {
      closestDiff = diff
      closest = c
    }
  }

  return closest?.scan || null
}

// Handle time selection - lookup from cache (instant!)
function handleTimeSelect(time) {
  isLive.value = false

  // Find closest scan for each scanner from cache
  const newScans = {}
  for (const scanner of props.availableScanners) {
    const key = `${scanner.scannerId}:${scanner.bandName}`
    const scan = findClosestInCache(key, time)
    if (scan) {
      newScans[key] = scan
    }
  }
  // Single reactive update
  historicalScans.value = newScans
}

function handleLive() {
  isLive.value = true
  historicalScans.value = {}
}

// Load timelines and scan cache when scanners change
watch(() => props.availableScanners, async () => {
  if (props.showTimeline) {
    loadTimelines()
    await loadScanCache()
  }
}, { immediate: true, deep: true })
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
          <span v-if="cacheLoading" class="text-gray-400 text-xs ml-2">
            Loading history...
          </span>
          <span v-else-if="!showingLive" class="text-yellow-400 text-xs ml-2">
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
      :max-hours="0.167"
      :height="50"
      :showing-live="showingLive"
      :current-time="currentDisplayTime"
      :last-scan-time="latestScanTime"
      :hide-markers="false"
      class="mt-3"
      @select="handleTimeSelect"
      @live="handleLive"
    />
  </div>
</template>
