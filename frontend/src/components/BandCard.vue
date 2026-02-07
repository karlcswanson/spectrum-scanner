<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import D3SpectrumChart from './D3SpectrumChart.vue'
import TimeScrubber from './TimeScrubber.vue'
import { formatFreqRange, isScanHistoryAvailable, fetchTimeline, fetchScanAtTime, fetchDecimatedScans, buildDecimatedCache, findClosestInCache } from '@lib'

const props = defineProps({
  band: { type: Object, required: true },
  scanBus: { type: Object, required: true },
  getScanData: { type: Function, required: true },
  getScanInfo: { type: Function, required: true },
  scanUpdateCount: { type: Number, default: 0 },
  onExport: { type: Function, default: null },
  // Enable timeline scrubber (requires local SQLite or API)
  showTimeline: { type: Boolean, default: true },
  timelineHours: { type: Number, default: 0.167 },  // 10 minutes
})

// Trace display modes
const showCurrent = ref(true)
const showAverage = ref(false)
const showPeak = ref(false)

// Chart ref for peak reset
const chartRef = ref(null)

// Historical playback state
const isLive = ref(true)
const historicalScan = ref(null)

// Timeline data (fetched from local API)
const timeline = ref([])
const decimatedCache = ref(new Map())

// Check if timeline feature is available
const timelineAvailable = computed(() => props.showTimeline && isScanHistoryAvailable())

// Are we showing live data right now?
const showingLive = computed(() => {
  return isLive.value && !!props.getScanData(props.band.name)
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

// Format frequency range for display
function formatBandRange() {
  return formatFreqRange(props.band.start_hz, props.band.stop_hz)
}

// Get band object for chart
function getBandForChart() {
  return {
    name: props.band.name,
    start_hz: props.band.start_hz,
    stop_hz: props.band.stop_hz,
  }
}

// Build traces for chart (live + historical)
const chartTraces = computed(() => {
  const traces = []

  // Historical trace (blue, when scrubbing)
  if (!isLive.value && historicalScan.value) {
    traces.push({
      id: `${props.band.name}-historical`,
      name: 'Historical',
      scan: {
        hz_lo: historicalScan.value.hz_lo,
        hz_hi: historicalScan.value.hz_hi,
        step: historicalScan.value.step,
        power: historicalScan.value.power,
      },
      color: '#00d4ff', // Blue/cyan for historical
    })
  }

  return traces
})

function resetPeakHold() {
  if (chartRef.value) {
    chartRef.value.resetAllPeaks()
  }
}

function handleExport() {
  if (props.onExport) {
    props.onExport(props.band.name)
  }
}

// Current time range (for refetching)
const currentTimeRange = ref({ hours: props.timelineHours })

// Load timeline and decimated cache
async function loadTimeline(options = null) {
  if (!timelineAvailable.value) return

  const rangeOpts = options || currentTimeRange.value
  const hours = rangeOpts.hours || props.timelineHours

  // Fetch timeline entries
  const entries = await fetchTimeline(props.band.name, hours)
  timeline.value = entries

  // Fetch decimated scans for fast preview during scrubbing
  const decimated = await fetchDecimatedScans(props.band.name, hours)
  console.log('[BandCard] loadTimeline: fetched', decimated.length, 'decimated scans')
  decimatedCache.value = buildDecimatedCache(decimated)
  console.log('[BandCard] loadTimeline: cache built with', decimatedCache.value.size, 'entries')
}

// Handle time range change from scrubber
async function handleRangeChange(rangeOpts) {
  currentTimeRange.value = rangeOpts
  await loadTimeline(rangeOpts)
}

// Preview handler (while dragging) - use decimated cache for speed
function handleTimePreview(time) {
  console.log('[BandCard] handleTimePreview:', time, 'cache size:', decimatedCache.value.size)
  isLive.value = false
  const scan = findClosestInCache(decimatedCache.value, time)
  console.log('[BandCard] findClosestInCache result:', scan ? `found with ${scan.power?.length} points` : 'NULL')
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

// Select handler (on release) - fetch full resolution scan from DB
async function handleTimeSelect(time) {
  isLive.value = false
  const scan = await fetchScanAtTime(props.band.name, time)
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

function handleLive() {
  isLive.value = true
  historicalScan.value = null
}

const hasScanData = () => !!props.getScanData(props.band.name)

// Load timeline on mount
onMounted(() => {
  console.log('[BandCard] onMounted for band:', props.band.name, 'timelineAvailable:', timelineAvailable.value, 'showTimeline:', props.showTimeline)
  loadTimeline()
})

// Reload timeline when band changes
watch(() => props.band.name, () => {
  loadTimeline()
})

// Refresh timeline when new scans arrive (if in live mode)
watch(() => props.scanUpdateCount, () => {
  if (isLive.value && timelineAvailable.value) {
    loadTimeline()
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
            ({{ formatBandRange() }})
          </span>
          <span v-if="!isLive" class="text-yellow-400 text-xs ml-2">
            Historical
          </span>
        </h2>
        <p class="text-xs text-gray-500" :data-v="scanUpdateCount">
          {{ getScanInfo(band.name) }}
        </p>
      </div>

      <div class="flex items-center gap-3">
        <!-- Trace toggles -->
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
          v-if="onExport"
          @click="handleExport"
          :disabled="!hasScanData()"
          class="px-4 py-2 rounded text-sm font-semibold transition-colors"
          :class="hasScanData()
            ? 'bg-green-500 hover:bg-green-600 text-black'
            : 'bg-gray-600 text-gray-400 cursor-not-allowed'"
        >
          Export CSV
        </button>
      </div>
    </div>

    <D3SpectrumChart
      ref="chartRef"
      :band-name="band.name"
      :scan-bus="scanBus"
      :get-scan-data="getScanData"
      :band="getBandForChart()"
      :traces="chartTraces"
      :height="300"
      :show-current="showCurrent"
      :show-average="showAverage && isLive"
      :show-peak="showPeak && isLive"
    />

    <!-- Timeline scrubber for historical playback -->
    <TimeScrubber
      v-if="timelineAvailable"
      :scanner-id="'local'"
      :band-name="band.name"
      :timeline="timeline"
      :max-hours="timelineHours"
      :height="50"
      :showing-live="showingLive"
      :current-time="currentDisplayTime"
      :tick="scanUpdateCount"
      class="mt-3"
      @preview="handleTimePreview"
      @select="handleTimeSelect"
      @live="handleLive"
      @range-change="handleRangeChange"
    />
  </div>
</template>
