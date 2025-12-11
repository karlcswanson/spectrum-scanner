<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useScannersStore } from '../stores/scanners'
import D3SpectrumChart from './D3SpectrumChart.vue'
import TimeScrubber from './TimeScrubber.vue'

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
})

const store = useScannersStore()
const chartRef = ref(null)

// Trace display modes
const showCurrent = ref(true)
const showAverage = ref(false)
const showPeak = ref(false)

// Historical playback state
const isLive = ref(true)
const timeline = ref([])
const historicalScan = ref(null)

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

const scanInfo = computed(() => {
  const scan = activeScan.value
  if (!scan?.power) return '--'
  const points = scan.power.length
  const minP = Math.min(...scan.power).toFixed(1)
  const maxP = Math.max(...scan.power).toFixed(1)
  return `${points} pts | ${minP} to ${maxP} dBm`
})

const freqRange = computed(() => {
  const start = (props.band.start_hz / 1e6).toFixed(0)
  const stop = (props.band.stop_hz / 1e6).toFixed(0)
  return `${start}-${stop} MHz`
})

// Build traces array for D3 chart
const traces = computed(() => {
  const result = []

  // Primary trace from this scanner
  if (activeScan.value) {
    result.push({
      id: props.scannerId,
      name: props.scannerName || props.scannerId,
      scan: activeScan.value,
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

// Timeline handlers
async function loadTimeline() {
  if (props.showTimeline) {
    // Convert hours to integer for API (minimum 1 hour for API, but we filter client-side)
    const apiHours = Math.max(1, Math.ceil(props.timelineHours))
    timeline.value = await store.fetchTimeline(props.scannerId, props.band.name, apiHours)
  }
}

async function handleTimeSelect(time) {
  isLive.value = false
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
}

// Check if we have valid live scan data
function hasLiveScan() {
  return props.scan && props.scan.power && props.scan.power.length > 0
}

// Load the most recent historical scan (as fallback, stays in live mode)
async function loadLatestHistorical() {
  if (timeline.value.length > 0) {
    const latestTime = new Date(timeline.value[timeline.value.length - 1].timestamp)
    // Load the scan but don't switch out of live mode - this is just a fallback
    const scan = await store.fetchScanAtTime(props.scannerId, latestTime, props.band.name)
    if (scan) {
      historicalScan.value = {
        hz_lo: scan.hz_lo,
        hz_hi: scan.hz_hi,
        step: scan.step_hz,
        power: scan.power,
        timestamp: scan.timestamp,
      }
    }
    // Keep isLive = true so we switch to live data when it arrives
  }
}

// Load timeline on mount if enabled, and fetch latest scan if no live data
onMounted(async () => {
  await loadTimeline()

  // If no live scan and we have timeline data, load the most recent scan
  if (!hasLiveScan()) {
    await loadLatestHistorical()
  }
})

// Reload timeline when band changes
watch(() => props.band.name, async () => {
  await loadTimeline()
  // Load latest historical if no live scan
  if (!hasLiveScan()) {
    await loadLatestHistorical()
  }
})

// Periodically refresh timeline
let timelineInterval = null
onMounted(() => {
  if (props.showTimeline) {
    timelineInterval = setInterval(loadTimeline, 60000) // Refresh every minute
  }
})
</script>

<template>
  <div class="bg-gray-800 rounded-lg p-4">
    <div class="flex justify-between items-start mb-3">
      <div>
        <h2 class="text-lg font-semibold text-cyan-400">
          {{ band.name }}
          <span class="text-gray-500 font-normal text-sm ml-2">
            ({{ freqRange }})
          </span>
          <span v-if="!showingLive && activeScan" class="text-yellow-400 text-xs ml-2">
            Historical
          </span>
        </h2>
        <p class="text-xs text-gray-500">
          <span v-if="showScanner && scannerName" class="mr-3">{{ scannerName }}</span>
          {{ scanInfo }}
        </p>
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
          :disabled="!activeScan"
          class="px-4 py-2 rounded text-sm font-semibold transition-colors"
          :class="activeScan
            ? 'bg-green-500 hover:bg-green-600 text-black'
            : 'bg-gray-600 text-gray-400 cursor-not-allowed'"
        >
          Export CSV
        </button>
      </div>
    </div>

    <D3SpectrumChart
      ref="chartRef"
      :traces="traces"
      :band="band"
      :height="height"
      :show-current="showCurrent"
      :show-average="showAverage"
      :show-peak="showPeak"
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
      class="mt-3"
      @select="handleTimeSelect"
      @live="handleLive"
    />
  </div>
</template>
