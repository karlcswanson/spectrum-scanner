<script setup>
import { ref, watch, onMounted, onUnmounted, nextTick } from 'vue'
import * as d3 from 'd3'

const props = defineProps({
  // Array of pinned frequencies: [{ freqHz, freqMHz, color }]
  pinnedFreqs: {
    type: Array,
    default: () => [],
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

const emit = defineEmits(['remove-freq'])

const container = ref(null)
const svgRef = ref(null)

const margin = { top: 10, right: 50, bottom: 30, left: 55 }
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

  return pins.map(pin => {
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

// Watch for data changes — shallow watch + debounce
let drawTimer = null
watch(() => [props.pinnedFreqs, props.scans, props.timeRange], () => {
  // Historical data changed — clear live buffer to avoid overlap
  liveBuffer = {}
  if (drawTimer) clearTimeout(drawTimer)
  drawTimer = setTimeout(updateChart, 200)
})

// Watch pinnedFreqs changes to prune stale keys from liveBuffer
watch(() => props.pinnedFreqs, (pins) => {
  if (!pins || pins.length === 0) {
    liveBuffer = {}
    return
  }
  const validKeys = new Set(pins.map(p => p.freqHz))
  for (const key of Object.keys(liveBuffer)) {
    if (!validKeys.has(Number(key))) delete liveBuffer[key]
  }
})

// Live scan watcher — append new data point for each pinned frequency
let liveDrawTimer = null
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
    // Trim to max size
    if (buf.length > LIVE_BUFFER_MAX) buf.splice(0, buf.length - LIVE_BUFFER_MAX)
  }

  // Debounce chart redraw for live updates (faster than historical — 100ms)
  if (liveDrawTimer) clearTimeout(liveDrawTimer)
  liveDrawTimer = setTimeout(updateChart, 100)
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
  if (liveDrawTimer) clearTimeout(liveDrawTimer)
})
</script>

<template>
  <div ref="container" class="frequency-time-plot w-full relative">
    <svg ref="svgRef" class="w-full rounded" :style="{ height: `${height}px` }"></svg>

    <!-- Legend with remove buttons -->
    <div class="flex flex-wrap gap-3 mt-1 px-1">
      <div
        v-for="pin in pinnedFreqs"
        :key="pin.freqHz"
        class="flex items-center gap-1 text-xs"
      >
        <span
          class="inline-block w-3 h-0.5 rounded"
          :style="{ backgroundColor: pin.color }"
        ></span>
        <span class="text-gray-400 font-mono">{{ pin.freqMHz.toFixed(3) }} MHz</span>
        <button
          @click="emit('remove-freq', pin)"
          class="text-gray-500 hover:text-red-400 ml-0.5 leading-none"
          title="Remove"
        >&times;</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.frequency-time-plot {
  position: relative;
}
</style>
