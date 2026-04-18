<script setup>
import { ref, computed, watch, onMounted, onUnmounted, nextTick } from 'vue'
import * as d3 from 'd3'

const props = defineProps({
  // Array of pinned frequencies: [{ freqHz, freqMHz, color, name?, isServer?, category?, notes? }]
  pinnedFreqs: {
    type: Array,
    default: () => [],
  },
  // Set of freqHz values that are selected (active)
  selectedFreqs: {
    type: Set,
    default: () => new Set(),
  },
  // Current active scan (for live power readout in legend)
  activeScan: {
    type: Object,
    default: null,
  },
  // Array of scan entries: [{ timestamp, scan: { hz_lo, hz_hi, power } }] or flat [{ timestamp, hz_lo, hz_hi, power }]
  scans: {
    type: Array,
    default: () => [],
  },
  // Fixed time range [startMs, endMs] to match waterfall/scrubber. If null, auto-fit from data.
  timeRange: {
    type: Array,
    default: null,
  },
  // Live scan object — when provided, each new value is appended to internal buffer
  liveScan: {
    type: Object,
    default: null,
  },
  // Whether we're in live mode (controls time range scrolling)
  isLive: {
    type: Boolean,
    default: true,
  },
})

const INTERFERENCE_THRESHOLD_DBM = -40

const emit = defineEmits(['remove-freq', 'toggle-freq', 'select-all-freqs', 'deselect-all-freqs'])

const container = ref(null)
const svgRef = ref(null)

const margin = { top: 10, right: 50, bottom: 30, left: 55 }
// Updated dynamically in buildStructure() for narrow screens
const height = 150

// Cached chart structure — built once, updated incrementally
let cache = {
  width: 0,
  plotWidth: 0,
  plotHeight: 0,
  chart: null,    // d3 selection
  xScale: null,
  yScale: null,
  lineGen: null,
  linesGroup: null,
  xAxisGroup: null,
  yAxisGroup: null,
  gridGroup: null,
}

// Internal buffer for live scan data points — keyed by freqHz
// { [freqHz]: [{ time, dbm }, ...] }
let liveBuffer = {}
const LIVE_BUFFER_MAX = 600 // ~10 min at 1 scan/sec

// Live power readout from activeScan for legend display
function getPinPower(pin) {
  const scan = props.activeScan
  if (!scan?.power?.length) return null
  const { hz_lo, hz_hi, power } = scan
  if (pin.freqHz < hz_lo || pin.freqHz > hz_hi) return null
  const idx = Math.round(((pin.freqHz - hz_lo) / (hz_hi - hz_lo)) * (power.length - 1))
  if (idx < 0 || idx >= power.length) return null
  return power[idx]
}

const livePowers = computed(() => {
  const scan = props.activeScan
  if (!scan?.power?.length) return {}
  const result = {}
  for (const pin of props.pinnedFreqs) {
    const p = getPinPower(pin)
    if (p !== null) result[pin.freqHz] = p
  }
  return result
})

const allSelected = computed(() => props.selectedFreqs.size >= props.pinnedFreqs.length && props.pinnedFreqs.length > 0)
const noneSelected = computed(() => props.selectedFreqs.size === 0)

// Extract dBm at each pinned frequency from a single scan object
function extractFromScan(scan, timestamp) {
  const power = scan.power
  if (!power || power.length === 0) return null
  const hz_lo = scan.hz_lo
  const hz_hi = scan.hz_hi
  const pins = props.pinnedFreqs
  const result = {}
  for (let i = 0; i < pins.length; i++) {
    const pin = pins[i]
    if (pin.freqHz < hz_lo || pin.freqHz > hz_hi) continue
    const idx = Math.round(((pin.freqHz - hz_lo) / (hz_hi - hz_lo)) * (power.length - 1))
    if (idx < 0 || idx >= power.length) continue
    result[pin.freqHz] = { time: timestamp, dbm: power[idx] }
  }
  return result
}

// Extract time-series data for all pinned frequencies from scans + live buffer
function extractSeries() {
  const scans = props.scans
  const pins = props.pinnedFreqs
  if (pins.length === 0) return []

  return pins.filter(pin => props.selectedFreqs.has(pin.freqHz)).map(pin => {
    const points = []

    // Historical scans
    for (let i = 0; i < scans.length; i++) {
      const entry = scans[i]
      const scan = entry.scan || entry
      const power = scan.power
      if (!power || power.length === 0) continue

      const hz_lo = scan.hz_lo
      const hz_hi = scan.hz_hi
      if (pin.freqHz < hz_lo || pin.freqHz > hz_hi) continue

      const idx = Math.round(((pin.freqHz - hz_lo) / (hz_hi - hz_lo)) * (power.length - 1))
      if (idx < 0 || idx >= power.length) continue

      const ts = entry.timestamp || new Date(scan.timestamp).getTime()
      points.push({ time: ts, dbm: power[idx] })
    }

    // Append live buffer points (already sorted by time)
    const livePoints = liveBuffer[pin.freqHz]
    if (livePoints && livePoints.length > 0) {
      // Avoid duplicates: only add live points newer than last historical point
      const lastHistTime = points.length > 0 ? points[points.length - 1].time : 0
      for (let j = 0; j < livePoints.length; j++) {
        if (livePoints[j].time > lastHistTime) {
          points.push(livePoints[j])
        }
      }
    }

    return { pin, points }
  })
}

// Build chart structure (axes, grid, groups) — called once or on resize
function buildStructure() {
  if (!svgRef.value || !container.value) return false

  const rect = container.value.getBoundingClientRect()
  const width = rect.width

  // Responsive margins matching D3SpectrumChart
  const isNarrow = width < 500
  margin.left = isNarrow ? 35 : 55
  margin.right = isNarrow ? 15 : 50

  const plotWidth = width - margin.left - margin.right
  const plotHeight = height - margin.top - margin.bottom

  if (plotWidth <= 0 || plotHeight <= 0) return false
  if (cache.width === width) return true // no rebuild needed

  const svg = d3.select(svgRef.value)
  svg.selectAll('*').remove()
  svg.attr('width', width).attr('height', height).style('background', '#0a0a1a')

  const chart = svg.append('g')
    .attr('transform', `translate(${margin.left},${margin.top})`)

  const gridGroup = chart.append('g').attr('class', 'grid')
  const xAxisGroup = chart.append('g').attr('class', 'x-axis')
    .attr('transform', `translate(0,${plotHeight})`)
  const yAxisGroup = chart.append('g').attr('class', 'y-axis')
  const linesGroup = chart.append('g').attr('class', 'lines')

  const xScale = d3.scaleTime().range([0, plotWidth])
  const yScale = d3.scaleLinear().range([plotHeight, 0])
  const lineGen = d3.line()
    .x(d => xScale(d.time))
    .y(d => yScale(d.dbm))
    .curve(d3.curveLinear)

  cache = { width, plotWidth, plotHeight, chart, xScale, yScale, lineGen, linesGroup, xAxisGroup, yAxisGroup, gridGroup }
  return true
}

// Update axes and paths with new data — fast incremental update
function updateChart() {
  if (!buildStructure()) return

  const { plotWidth, plotHeight, xScale, yScale, lineGen, linesGroup, xAxisGroup, yAxisGroup, gridGroup } = cache

  const series = extractSeries()
  if (series.length === 0) {
    linesGroup.selectAll('*').remove()
    return
  }

  // Compute domains
  const allTimes = series.flatMap(s => s.points.map(p => p.time))
  const allDbm = series.flatMap(s => s.points.map(p => p.dbm))

  if (allTimes.length === 0) {
    linesGroup.selectAll('*').remove()
    return
  }

  let xDomain
  if (props.timeRange) {
    // Use fixed time range from waterfall/scrubber, but extend to now if live
    xDomain = props.isLive
      ? [props.timeRange[0], Math.max(props.timeRange[1], d3.max(allTimes))]
      : [props.timeRange[0], props.timeRange[1]]
  } else {
    xDomain = [d3.min(allTimes), d3.max(allTimes)]
  }

  const dbMin = Math.min(-110, d3.min(allDbm) - 5)
  const dbMax = Math.max(-20, d3.max(allDbm) + 5)

  xScale.domain(xDomain)
  yScale.domain([dbMin, dbMax])

  // Update grid
  gridGroup.selectAll('*').remove()
  const dbStep = 20
  for (let db = Math.ceil(dbMin / dbStep) * dbStep; db <= dbMax; db += dbStep) {
    gridGroup.append('line')
      .attr('x1', 0).attr('y1', yScale(db))
      .attr('x2', plotWidth).attr('y2', yScale(db))
      .attr('stroke', '#1a1a3e').attr('stroke-width', 1)
  }

  // Update axes
  xAxisGroup.call(d3.axisBottom(xScale).ticks(6).tickFormat(d3.timeFormat('%H:%M:%S')))
  xAxisGroup.selectAll('text').attr('fill', '#666').style('font-size', '9px')
  xAxisGroup.selectAll('line').attr('stroke', '#666')
  xAxisGroup.select('.domain').attr('stroke', '#666')

  yAxisGroup.call(d3.axisLeft(yScale).ticks(5).tickFormat(d => `${d}`))
  yAxisGroup.selectAll('text').attr('fill', '#666').style('font-size', '9px')
  yAxisGroup.selectAll('line').attr('stroke', '#666')
  yAxisGroup.select('.domain').attr('stroke', '#666')

  // Update line paths — D3 enter/update/exit pattern
  const paths = linesGroup.selectAll('path').data(series, d => d.pin.freqHz)

  // Exit
  paths.exit().remove()

  // Enter + update
  paths.enter()
    .append('path')
    .attr('fill', 'none')
    .attr('stroke-width', 1.5)
    .attr('opacity', 0.9)
    .merge(paths)
    .attr('stroke', d => d.pin.color)
    .attr('d', d => d.points.length >= 2 ? lineGen(d.points) : null)
}

// Unified debounced redraw — single timer prevents redundant double-draws
let drawTimer = null
function scheduleRedraw(delayMs = 200) {
  if (drawTimer) clearTimeout(drawTimer)
  drawTimer = setTimeout(updateChart, delayMs)
}

// Historical data or time range changed — clear live buffer to avoid overlap
watch(() => [props.scans, props.timeRange], () => {
  liveBuffer = {}
  scheduleRedraw()
})

// Selection changed — redraw to show/hide lines
watch(() => props.selectedFreqs, () => {
  scheduleRedraw(50)
})

// Pinned frequencies changed — prune stale keys, keep live data for remaining pins
watch(() => props.pinnedFreqs, (pins) => {
  if (!pins || pins.length === 0) {
    liveBuffer = {}
  } else {
    const validKeys = new Set(pins.map(p => p.freqHz))
    for (const key of Object.keys(liveBuffer)) {
      if (!validKeys.has(Number(key))) delete liveBuffer[key]
    }
  }
  scheduleRedraw()
})

// Live scan watcher — append new data point for each pinned frequency
watch(() => props.liveScan, (scan) => {
  if (!scan || !props.isLive || props.pinnedFreqs.length === 0) return

  const ts = scan._receivedAt || Date.now()
  const extracted = extractFromScan(scan, ts)
  if (!extracted) return

  for (const pin of props.pinnedFreqs) {
    const pt = extracted[pin.freqHz]
    if (!pt) continue
    if (!liveBuffer[pin.freqHz]) liveBuffer[pin.freqHz] = []
    const buf = liveBuffer[pin.freqHz]
    buf.push(pt)
    if (buf.length > LIVE_BUFFER_MAX) buf.splice(0, buf.length - LIVE_BUFFER_MAX)
  }

  scheduleRedraw(100) // faster debounce for live updates
})

// Resize handling
let resizeObserver = null

onMounted(() => {
  nextTick(() => updateChart())
  if (container.value) {
    resizeObserver = new ResizeObserver(() => {
      cache.width = 0 // force rebuild
      updateChart()
    })
    resizeObserver.observe(container.value)
  }
})

onUnmounted(() => {
  if (resizeObserver) resizeObserver.disconnect()
  if (drawTimer) clearTimeout(drawTimer)
})
</script>

<template>
  <div ref="container" class="frequency-time-plot w-full relative">
    <svg ref="svgRef" class="w-full rounded" :style="{ height: `${height}px` }"></svg>

    <!-- Legend with selection toggles and live power -->
    <div class="flex flex-wrap items-center gap-1 mt-1 px-1">
      <div
        v-for="pin in pinnedFreqs"
        :key="pin.freqHz"
        class="pin-legend-item"
        :class="{
          'pin-selected': selectedFreqs.has(pin.freqHz),
          'pin-unselected': !selectedFreqs.has(pin.freqHz),
          'pin-alert': livePowers[pin.freqHz] > INTERFERENCE_THRESHOLD_DBM && selectedFreqs.has(pin.freqHz),
        }"
        @click="emit('toggle-freq', pin.freqHz)"
        :title="pin.notes || (selectedFreqs.has(pin.freqHz) ? 'Click to deselect' : 'Click to select')"
      >
        <span
          class="pin-dot"
          :class="{ 'animate-pulse': livePowers[pin.freqHz] > INTERFERENCE_THRESHOLD_DBM && selectedFreqs.has(pin.freqHz) }"
          :style="{ background: livePowers[pin.freqHz] > INTERFERENCE_THRESHOLD_DBM && selectedFreqs.has(pin.freqHz) ? '#ef4444' : pin.color }"
        ></span>
        <span v-if="pin.name" class="pin-name">{{ pin.name }}</span>
        <span class="pin-freq">{{ pin.freqMHz.toFixed(3) }}</span>
        <span
          class="pin-power"
          :class="{ 'text-red-400 font-bold': livePowers[pin.freqHz] > INTERFERENCE_THRESHOLD_DBM }"
        >{{ livePowers[pin.freqHz] != null ? livePowers[pin.freqHz].toFixed(1) : '--' }}</span>
        <button
          v-if="!pin.isServer"
          @click.stop="emit('remove-freq', pin)"
          class="text-gray-600 hover:text-red-400 leading-none"
          title="Remove"
        >&times;</button>
      </div>
      <!-- All / None buttons -->
      <div v-if="pinnedFreqs.length > 1" class="flex items-center gap-1 ml-auto text-[10px]">
        <button
          @click="emit('select-all-freqs')"
          class="px-1.5 py-0.5 rounded transition-colors"
          :class="allSelected ? 'bg-gray-700 text-gray-500 cursor-default' : 'bg-gray-700 text-gray-300 hover:bg-gray-600'"
          :disabled="allSelected"
        >All</button>
        <button
          @click="emit('deselect-all-freqs')"
          class="px-1.5 py-0.5 rounded transition-colors"
          :class="noneSelected ? 'bg-gray-700 text-gray-500 cursor-default' : 'bg-gray-700 text-gray-300 hover:bg-gray-600'"
          :disabled="noneSelected"
        >None</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.frequency-time-plot {
  position: relative;
  touch-action: manipulation;
  -webkit-touch-callout: none;
  -webkit-user-select: none;
  user-select: none;
}

.pin-legend-item {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 11px;
  cursor: pointer;
  background: #1f2937;
  transition: opacity 0.15s, background 0.15s;
  min-width: 0;
}

.pin-legend-item:hover {
  background: #374151;
}

.pin-unselected {
  opacity: 0.45;
}

.pin-selected {
  background: #1e3a5f;
}

.pin-alert {
  background: #7f1d1d40;
}

.pin-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  flex-shrink: 0;
}

.pin-name {
  color: #d1d5db;
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 80px;
}

.pin-freq {
  color: #6b7280;
  font-family: monospace;
  font-size: 10px;
  flex-shrink: 0;
}

.pin-power {
  color: #9ca3af;
  font-family: monospace;
  font-weight: 600;
  min-width: 32px;
  text-align: right;
  flex-shrink: 0;
}
</style>
