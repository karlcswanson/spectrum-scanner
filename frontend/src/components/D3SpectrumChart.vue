<script setup>
import { ref, watch, onMounted, onUnmounted, computed } from 'vue'
import * as d3 from 'd3'
// Import worker using Vite's ?worker&inline syntax for Wails compatibility
// This embeds the worker as a blob URL instead of a separate file
import TraceWorker from '../lib/traceWorker.js?worker&inline'
import { logger } from '@lib'

const props = defineProps({
  // Array of traces to display: [{ id, name, scan, color }]
  traces: {
    type: Array,
    default: () => [],
  },
  // Single scan for backward compatibility (wrapped as trace internally)
  scan: {
    type: Object,
    default: null,
  },
  band: {
    type: Object,
    default: null,
  },
  height: {
    type: Number,
    default: 300,
  },
  // Display modes for trace processing
  showCurrent: {
    type: Boolean,
    default: true,
  },
  showAverage: {
    type: Boolean,
    default: false,
  },
  showPeak: {
    type: Boolean,
    default: false,
  },
  // Event bus mode (for desktop app performance)
  bandName: {
    type: String,
    default: null,
  },
  scanBus: {
    type: Object,
    default: null,
  },
  getScanData: {
    type: Function,
    default: null,
  },
  // External cursor frequency (Hz) from another chart
  cursorFreq: {
    type: Number,
    default: null,
  },
  // Pinned frequencies for time-series: [{ freqHz, freqMHz, color }]
  pinnedFreqs: {
    type: Array,
    default: () => [],
  },
})

const emit = defineEmits(['zoom', 'cursor-move', 'freq-pin'])

const container = ref(null)
const svgRef = ref(null)

// Cursor state for tooltip
const cursorInfo = ref(null)

// Web worker for trace calculations
let traceWorker = null
const workerResults = {} // { traceId: { peak, avg } }

// Color palette for multiple traces
const colorPalette = d3.schemeCategory10

// Sanitize string for use as CSS class name (handles spaces, dots, special chars)
function sanitizeClass(str) {
  return String(str).replace(/[^a-zA-Z0-9]/g, '-')
}

// For event bus mode, store current scan data (non-reactive)
let currentScanData = null

// Interference threshold
const INTERFERENCE_THRESHOLD_DBM = -40

// dB scale constants
const minDb = -110
const maxDb = -20

// Initialize web worker
function initWorker() {
  if (typeof Worker !== 'undefined') {
    try {
      traceWorker = new TraceWorker()
      traceWorker.onmessage = (e) => {
        const { type, traceId, peak, avg } = e.data
        if (type === 'result') {
          workerResults[traceId] = { peak, avg }
          // Trigger redraw with new peak/avg data
          updateTraces()
        }
      }
    } catch (err) {
      logger.warn('Failed to initialize trace worker:', err)
      traceWorker = null
    }
  }
}

// Get traces - combine event bus mode, explicit traces, and legacy props
// Order matters for z-index: first added = drawn first = behind
function getTracesForDraw() {
  const result = []

  // Add explicit traces first (e.g., historical scans from scrubber)
  // These are drawn behind live trace
  if (props.traces.length > 0) {
    for (const [idx, trace] of props.traces.entries()) {
      result.push({
        id: trace.id || `trace-${idx}`,
        name: trace.name || `Scanner ${idx + 1}`,
        scan: trace.scan,
        color: trace.color || colorPalette[idx % colorPalette.length],
        isLive: false,  // Explicit traces always render
      })
    }
  }

  // Event bus mode: add live scan last so it renders on top
  if (props.bandName && props.getScanData && props.showCurrent) {
    const scan = currentScanData
    if (scan?.power?.length > 0) {
      result.push({
        id: props.bandName,
        name: 'Live',
        scan: scan,
        color: '#22c55e',  // Green for live/current
        isLive: true,  // Flag to indicate this is a live trace (respects showCurrent)
      })
    }
  }

  // Legacy single scan prop
  if (result.length === 0 && props.scan?.power?.length > 0) {
    result.push({
      id: 'default',
      name: 'Scanner',
      scan: props.scan,
      color: '#22c55e',  // Green for live/current
      isLive: true,
    })
  }

  return result
}

// ATSC TV channels (VHF + UHF) for band labeling. Each channel is 6 MHz wide.
// VHF Low (2-6) has a 72-76 MHz gap between ch 4 and 5; VHF High (7-13) is
// contiguous from 174 MHz; UHF (14-51) is one continuous 6 MHz grid from 470
// MHz, except ch 37 (608-614) which is the radio-astronomy guard band. The
// same UHF grid extends through ch 69 (ends at 806 MHz) if ever needed.
function atscChannelStartMHz(ch) {
  if (ch >= 2  && ch <= 6)               return [54, 60, 66, 76, 82][ch - 2]
  if (ch >= 7  && ch <= 13)              return 174 + (ch - 7)  * 6
  if (ch >= 14 && ch <= 51 && ch !== 37) return 470 + (ch - 14) * 6
  return null
}

function getATSCChannels(startMHz, stopMHz) {
  const channels = []
  for (let ch = 2; ch <= 51; ch++) {
    const chStartMHz = atscChannelStartMHz(ch)
    if (chStartMHz === null) continue
    const chEndMHz = chStartMHz + 6
    const chCenterMHz = chStartMHz + 3
    if (chEndMHz > startMHz && chStartMHz < stopMHz) {
      channels.push({ num: ch, start: chStartMHz, end: chEndMHz, center: chCenterMHz })
    }
  }
  return channels
}

// WiFi 2.4 GHz channels
function getWifi24Channels(startMHz, stopMHz) {
  const channelCenters = {
    1: 2412, 2: 2417, 3: 2422, 4: 2427, 5: 2432, 6: 2437, 7: 2442,
    8: 2447, 9: 2452, 10: 2457, 11: 2462, 12: 2467, 13: 2472, 14: 2484
  }
  const nonOverlapping = [1, 6, 11]
  const channelWidth = 22

  const channels = []
  for (const [ch, center] of Object.entries(channelCenters)) {
    const lo = center - channelWidth / 2
    const hi = center + channelWidth / 2
    if (hi >= startMHz && lo <= stopMHz) {
      channels.push({
        num: parseInt(ch),
        center: center,
        lo: lo,
        hi: hi,
        primary: nonOverlapping.includes(parseInt(ch))
      })
    }
  }
  return channels
}

// DECT carriers — 1.728 MHz spacing on the ETSI grid
// Works for: EU (1880-1900), US/UPCS (1920-1930), Brazil (1910-1920),
// Japan (1893-1906), and expanded bands (e.g. EU+US 1880-1930)
function getDECTChannels(startMHz, stopMHz) {
  // Only activate for bands overlapping the DECT range (1880-1935 MHz)
  const dectLo = 1880
  const dectHi = 1935
  if (startMHz > dectHi || stopMHz < dectLo) return []

  const spacing = 1.728
  const gridBase = 1881.792 // ETSI carrier 9 center (lowest EU carrier)
  const channels = []

  // Clamp search to the DECT range
  const lo = Math.max(startMHz, dectLo)
  const hi = Math.min(stopMHz, dectHi)

  const firstN = Math.ceil((lo - gridBase + spacing / 2) / spacing)
  const lastN = Math.floor((hi - gridBase - spacing / 2) / spacing)

  for (let n = firstN; n <= lastN; n++) {
    const center = gridBase + n * spacing
    const cLo = center - spacing / 2
    const cHi = center + spacing / 2
    if (cHi > startMHz && cLo < stopMHz) {
      channels.push({ num: channels.length + 1, center, lo: cLo, hi: cHi })
    }
  }
  return channels
}

// Cache for chart structure
let chartCache = {
  width: 0,
  height: 0,
  startHz: 0,
  stopHz: 0,
  xScale: null,
  xScaleBase: null,
  yScale: null,
  margin: null,
  plotWidth: 0,
  plotHeight: 0,
  lineGenerator: null,
  zoomBehavior: null,
  isNarrow: false,
  lastZoomTransform: null, // persists across rebuilds
}

// Build or rebuild the chart structure (axes, grid, etc.)
function buildChartStructure() {
  if (!svgRef.value || !container.value) return false

  const rect = container.value.getBoundingClientRect()
  const width = rect.width
  const height = props.height
  const isNarrow = width < 500
  const margin = {
    top: isNarrow ? 15 : 20,
    right: isNarrow ? 15 : 50,
    bottom: isNarrow ? 35 : 50,
    left: isNarrow ? 35 : 55,
  }
  const plotWidth = width - margin.left - margin.right
  const plotHeight = height - margin.top - margin.bottom

  // Determine frequency range
  let startHz, stopHz
  const validTraces = getTracesForDraw().filter(t => t.scan?.power?.length > 0)

  if (validTraces.length > 0) {
    startHz = validTraces[0].scan.hz_lo
    stopHz = validTraces[0].scan.hz_hi
    for (let i = 1; i < validTraces.length; i++) {
      if (validTraces[i].scan.hz_lo < startHz) startHz = validTraces[i].scan.hz_lo
      if (validTraces[i].scan.hz_hi > stopHz) stopHz = validTraces[i].scan.hz_hi
    }
  } else if (props.band) {
    startHz = props.band.start_hz
    stopHz = props.band.stop_hz
  } else {
    startHz = 470e6
    stopHz = 608e6
  }

  // Check if rebuild needed
  const needsRebuild = chartCache.width !== width ||
    chartCache.height !== height ||
    chartCache.startHz !== startHz ||
    chartCache.stopHz !== stopHz

  if (!needsRebuild) return true

  // Save zoom transform before clearing SVG so we can restore after resize.
  // Only restore if frequency range is unchanged (resize case) — if the band
  // changed the old transform doesn't make sense on a new scale.
  let savedTransform = null
  const rangeUnchanged = chartCache.startHz === startHz && chartCache.stopHz === stopHz
  if (rangeUnchanged && chartCache.lastZoomTransform) {
    const t = chartCache.lastZoomTransform
    if (t.k !== 1 || t.x !== 0) savedTransform = t
  }

  const startMHz = startHz / 1e6
  const stopMHz = stopHz / 1e6
  const spanMHz = stopMHz - startMHz

  const atscChannels = getATSCChannels(startMHz, stopMHz)
  const wifi24Channels = getWifi24Channels(startMHz, stopMHz)
  const dectChannels = getDECTChannels(startMHz, stopMHz)
  const isUHF = atscChannels.length > 0
  const isWifi24 = wifi24Channels.length >= 3
  const isDECT = dectChannels.length >= 3

  const svg = d3.select(svgRef.value)
  svg.selectAll('*').remove()

  svg
    .attr('width', width)
    .attr('height', height)
    .style('background', '#0a0a1a')

  // Clip path so traces don't bleed outside plot area when zoomed
  svg.append('defs').append('clipPath')
    .attr('id', 'plot-clip')
    .append('rect')
    .attr('width', plotWidth)
    .attr('height', plotHeight)

  const chart = svg
    .append('g')
    .attr('transform', `translate(${margin.left},${margin.top})`)

  const xScale = d3.scaleLinear()
    .domain([startHz, stopHz])
    .range([0, plotWidth])

  const yScale = d3.scaleLinear()
    .domain([minDb, maxDb])
    .range([plotHeight, 0])

  // Grid (v-grid redrawn on zoom, h-grid stays fixed)
  const gridGroup = chart.append('g').attr('class', 'grid')
  const vGridGroup = gridGroup.append('g').attr('class', 'v-grid')
  const hGridGroup = gridGroup.append('g').attr('class', 'h-grid')

  // Vertical grid lines (will be redrawn on zoom)
  drawVerticalGrid(vGridGroup, xScale, plotHeight, startMHz, stopMHz, atscChannels, wifi24Channels, dectChannels, isUHF, isWifi24, isDECT)

  // Horizontal grid (fixed, not affected by zoom)
  const dbStep = 20
  for (let db = minDb; db <= maxDb; db += dbStep) {
    hGridGroup.append('line')
      .attr('x1', 0).attr('y1', yScale(db))
      .attr('x2', plotWidth).attr('y2', yScale(db))
      .attr('stroke', '#1a1a3e').attr('stroke-width', 1)
  }

  // X-axis (redrawn on zoom)
  const xAxisGroup = chart.append('g')
    .attr('class', 'x-axis')
    .attr('transform', `translate(0,${plotHeight})`)

  // Channel labels (redrawn on zoom)
  const channelGroup = chart.append('g')
    .attr('class', 'channel-labels')
    .attr('transform', `translate(0,${plotHeight + (isNarrow ? 20 : 28)})`)

  drawXAxis(xAxisGroup, channelGroup, xScale, plotWidth, startMHz, stopMHz, atscChannels, wifi24Channels, dectChannels, isUHF, isWifi24, isDECT)

  // Y-axis
  const yAxisGroup = chart.append('g')
  const axisFontSize = isNarrow ? '8px' : '10px'
  const yTickStep = isNarrow ? 30 : dbStep
  yAxisGroup.call(d3.axisLeft(yScale).tickValues(d3.range(minDb, maxDb + 1, yTickStep)).tickFormat(d => `${d}`))
  yAxisGroup.selectAll('text').attr('fill', '#666').style('font-size', axisFontSize)
  yAxisGroup.selectAll('line').attr('stroke', '#666')
  yAxisGroup.select('.domain').attr('stroke', '#666')

  // Axis labels
  chart.append('text')
    .attr('transform', 'rotate(-90)')
    .attr('x', -plotHeight / 2).attr('y', isNarrow ? -25 : -40)
    .attr('text-anchor', 'middle').attr('fill', '#666')
    .style('font-size', axisFontSize).text('dBm')

  chart.append('text')
    .attr('x', plotWidth / 2).attr('y', plotHeight + (isNarrow ? 28 : 42))
    .attr('text-anchor', 'middle').attr('fill', '#666')
    .style('font-size', axisFontSize).text('MHz')

  // Category band group (between grid and traces)
  chart.append('g').attr('class', 'category-bands')
    .attr('clip-path', 'url(#plot-clip)')

  // Traces group - clipped to plot area so zoomed traces don't bleed
  chart.append('g').attr('class', 'traces')
    .attr('clip-path', 'url(#plot-clip)')

  // Legend group
  svg.append('g').attr('class', 'legend')
    .attr('transform', `translate(${width - margin.right - 10}, ${margin.top + 10})`)

  // Cursor overlay
  const cursorGroup = chart.append('g').attr('class', 'cursor-overlay')
  cursorGroup.append('line').attr('class', 'cursor-line-v')
    .attr('y1', 0).attr('y2', plotHeight)
    .attr('stroke', '#666').attr('stroke-width', 1)
    .attr('stroke-dasharray', '4,4').attr('opacity', 0)
  cursorGroup.append('line').attr('class', 'cursor-line-h')
    .attr('x1', 0).attr('x2', plotWidth)
    .attr('stroke', '#666').attr('stroke-width', 1)
    .attr('stroke-dasharray', '4,4').attr('opacity', 0)
  cursorGroup.append('circle').attr('class', 'cursor-dot')
    .attr('r', 4).attr('fill', '#00d4ff').attr('opacity', 0)

  // Mouse overlay
  chart.append('rect').attr('class', 'mouse-overlay')
    .attr('width', plotWidth).attr('height', plotHeight)
    .attr('fill', 'transparent').attr('pointer-events', 'all')
    .style('cursor', 'crosshair')

  // Line generator
  const lineGenerator = d3.line()
    .x(d => d.x)
    .y(d => d.y)
    .curve(d3.curveLinear)

  // Store base scale (immutable copy for zoom rescaling)
  const xScaleBase = xScale.copy()

  // Zoom behavior — x-axis only, scroll wheel + touch pinch (no mouse drag — brush handles that)
  const zoomBehavior = d3.zoom()
    .scaleExtent([1, 20])
    .translateExtent([[0, 0], [plotWidth, plotHeight]])
    .extent([[0, 0], [plotWidth, plotHeight]])
    .filter((event) => {
      if (event.type === 'dblclick') return false
      // Block drag when Shift is held (brush handles Shift+drag)
      if (event.type === 'mousedown' && event.shiftKey) return false
      return true
    })
    .on('zoom', (event) => {
      chartCache.xScale = event.transform.rescaleX(xScaleBase)
      chartCache.lastZoomTransform = event.transform
      updateAxisAndGrid()
      updateTraces()
      drawCategoryBands()
      drawPinnedMarkers()
      emit('zoom', chartCache.xScale.domain())
    })

  // Brush-to-zoom: Shift+drag selects a frequency range, then zooms into it
  const brushGroup = chart.append('g').attr('class', 'brush')
  const brushBehavior = d3.brushX()
    .extent([[0, 0], [plotWidth, plotHeight]])
    .filter((event) => event.shiftKey) // only activate on Shift+drag
    .on('end', (event) => {
      if (!event.selection) return
      const [x0, x1] = event.selection
      brushGroup.call(brushBehavior.move, null)
      if (x1 - x0 < 10) return
      const newLo = chartCache.xScale.invert(x0)
      const newHi = chartCache.xScale.invert(x1)
      const k = (stopHz - startHz) / (newHi - newLo)
      const tx = -xScaleBase(newLo) * k
      zoomEl.transition().duration(300)
        .call(zoomBehavior.transform, d3.zoomIdentity.translate(tx, 0).scale(k))
    })
  brushGroup.call(brushBehavior)
  brushGroup.select('.selection')
    .attr('fill', '#00d4ff')
    .attr('fill-opacity', 0.15)
    .attr('stroke', '#00d4ff')
    .attr('stroke-opacity', 0.5)

  // Attach zoom to the brush overlay (topmost SVG element that receives all events).
  // The zoom filter allows normal drag (pan) but blocks Shift+drag (brush handles that).
  const zoomEl = brushGroup.select('.overlay')
  zoomEl.call(zoomBehavior)

  // Double-click to reset zoom
  zoomEl.on('dblclick', () => {
    zoomEl.transition().duration(300)
      .call(zoomBehavior.transform, d3.zoomIdentity)
  })

  // Update cache BEFORE zoom restore — the restore fires the zoom handler
  // synchronously, which sets chartCache.xScale to the zoomed scale.
  // If we update cache after, the zoomed xScale is overwritten with the base scale.
  chartCache = { width, height, startHz, stopHz, xScale, xScaleBase, yScale, margin, plotWidth, plotHeight, lineGenerator, zoomBehavior, isNarrow, lastZoomTransform: chartCache.lastZoomTransform }

  // Restore zoom transform from before rebuild (e.g. resize)
  // This fires the zoom handler synchronously, updating chartCache.xScale
  if (savedTransform) {
    zoomEl.call(zoomBehavior.transform, savedTransform)
  }

  // Setup mouse handlers
  setupMouseHandlers()

  return true
}

// Draw vertical grid lines for the given xScale
function drawVerticalGrid(group, xScale, plotHeight, startMHz, stopMHz, atscChannels, wifi24Channels, dectChannels, isUHF, isWifi24, isDECT) {
  group.selectAll('*').remove()
  const spanMHz = stopMHz - startMHz

  if (isUHF) {
    atscChannels.forEach((ch, idx) => {
      if (ch.start >= startMHz) {
        group.append('line')
          .attr('x1', xScale(ch.start * 1e6)).attr('y1', 0)
          .attr('x2', xScale(ch.start * 1e6)).attr('y2', plotHeight)
          .attr('stroke', '#1a1a3e').attr('stroke-width', 1)
      }
      if (idx === atscChannels.length - 1 && ch.end <= stopMHz) {
        group.append('line')
          .attr('x1', xScale(ch.end * 1e6)).attr('y1', 0)
          .attr('x2', xScale(ch.end * 1e6)).attr('y2', plotHeight)
          .attr('stroke', '#1a1a3e').attr('stroke-width', 1)
      }
    })
  } else if (isDECT) {
    dectChannels.forEach(ch => {
      // Carrier boundary lines
      group.append('line')
        .attr('x1', xScale(ch.lo * 1e6)).attr('y1', 0)
        .attr('x2', xScale(ch.lo * 1e6)).attr('y2', plotHeight)
        .attr('stroke', '#2a1a3e').attr('stroke-width', 1)
      // Subtle carrier fill on odd carriers for visual separation
      if (ch.num % 2 === 0) {
        group.append('rect')
          .attr('x', xScale(ch.lo * 1e6)).attr('y', 0)
          .attr('width', xScale(ch.hi * 1e6) - xScale(ch.lo * 1e6))
          .attr('height', plotHeight)
          .attr('fill', '#1a1a2e').attr('opacity', 0.4)
      }
    })
    // Final boundary
    const last = dectChannels[dectChannels.length - 1]
    if (last) {
      group.append('line')
        .attr('x1', xScale(last.hi * 1e6)).attr('y1', 0)
        .attr('x2', xScale(last.hi * 1e6)).attr('y2', plotHeight)
        .attr('stroke', '#2a1a3e').attr('stroke-width', 1)
    }
  } else if (isWifi24) {
    wifi24Channels.filter(ch => ch.primary).forEach(ch => {
      group.append('rect')
        .attr('x', xScale(ch.lo * 1e6)).attr('y', 0)
        .attr('width', xScale(ch.hi * 1e6) - xScale(ch.lo * 1e6))
        .attr('height', plotHeight)
        .attr('fill', '#1a2a24').attr('opacity', 0.5)
    })
    wifi24Channels.forEach(ch => {
      const lineColor = ch.primary ? '#2a5a4e' : '#1a1a3e'
      group.append('line')
        .attr('x1', xScale(ch.lo * 1e6)).attr('y1', 0)
        .attr('x2', xScale(ch.lo * 1e6)).attr('y2', plotHeight)
        .attr('stroke', lineColor).attr('stroke-width', ch.primary ? 1 : 0.5)
      group.append('line')
        .attr('x1', xScale(ch.hi * 1e6)).attr('y1', 0)
        .attr('x2', xScale(ch.hi * 1e6)).attr('y2', plotHeight)
        .attr('stroke', lineColor).attr('stroke-width', ch.primary ? 1 : 0.5)
    })
  } else {
    const freqStep = spanMHz > 100 ? 20 : spanMHz > 50 ? 10 : spanMHz > 20 ? 5 : spanMHz > 10 ? 2 : 1
    for (let f = Math.ceil(startMHz / freqStep) * freqStep; f <= stopMHz; f += freqStep) {
      group.append('line')
        .attr('x1', xScale(f * 1e6)).attr('y1', 0)
        .attr('x2', xScale(f * 1e6)).attr('y2', plotHeight)
        .attr('stroke', '#1a1a3e').attr('stroke-width', 1)
    }
  }
}

// Draw x-axis ticks and channel labels for the given xScale
function drawXAxis(xAxisGroup, channelGroup, xScale, plotWidth, startMHz, stopMHz, atscChannels, wifi24Channels, dectChannels, isUHF, isWifi24, isDECT) {
  xAxisGroup.selectAll('*').remove()
  channelGroup.selectAll('*').remove()

  if (isUHF) {
    const tickValues = []
    atscChannels.forEach((ch, idx) => {
      if (ch.start >= startMHz) tickValues.push(ch.start * 1e6)
      if (idx === atscChannels.length - 1 && ch.end <= stopMHz) tickValues.push(ch.end * 1e6)
    })
    xAxisGroup.call(d3.axisBottom(xScale).tickValues(tickValues).tickFormat(d => (d / 1e6).toFixed(0)))

    const chFontSize = chartCache.isNarrow ? '7px' : '9px'
    atscChannels.forEach(ch => {
      const x = xScale(ch.center * 1e6)
      if (x > 10 && x < plotWidth - 10) {
        channelGroup.append('text')
          .attr('x', x).attr('y', 0).attr('text-anchor', 'middle')
          .attr('fill', '#00d4ff').style('font-size', chFontSize).text(ch.num)
      }
    })
  } else if (isDECT) {
    // Tick at each carrier boundary
    const tickValues = []
    dectChannels.forEach((ch, idx) => {
      tickValues.push(ch.lo * 1e6)
      if (idx === dectChannels.length - 1) tickValues.push(ch.hi * 1e6)
    })
    xAxisGroup.call(d3.axisBottom(xScale).tickValues(tickValues).tickFormat(d => (d / 1e6).toFixed(1)))

    // Carrier number labels
    const chFontSize = chartCache.isNarrow ? '7px' : '9px'
    dectChannels.forEach(ch => {
      const x = xScale(ch.center * 1e6)
      if (x > 10 && x < plotWidth - 10) {
        channelGroup.append('text')
          .attr('x', x).attr('y', 0).attr('text-anchor', 'middle')
          .attr('fill', '#a855f7').style('font-size', chFontSize).text(`C${ch.num}`)
      }
    })
  } else if (isWifi24) {
    const tickValues = []
    wifi24Channels.filter(ch => ch.primary).forEach((ch, idx, arr) => {
      if (ch.lo >= startMHz) tickValues.push(ch.lo * 1e6)
      if (idx === arr.length - 1 && ch.hi <= stopMHz) tickValues.push(ch.hi * 1e6)
    })
    xAxisGroup.call(d3.axisBottom(xScale).tickValues(tickValues).tickFormat(d => (d / 1e6).toFixed(0)))

    const wiFontSize = chartCache.isNarrow ? '7px' : '9px'
    wifi24Channels.forEach(ch => {
      const x = xScale(ch.center * 1e6)
      if (x > 10 && x < plotWidth - 10) {
        channelGroup.append('text')
          .attr('x', x).attr('y', 0).attr('text-anchor', 'middle')
          .attr('fill', ch.primary ? '#22c55e' : '#666')
          .attr('font-weight', ch.primary ? 'bold' : 'normal')
          .style('font-size', wiFontSize).text(ch.num)
      }
    })
  } else {
    const tickCount = chartCache.isNarrow ? 5 : 10
    xAxisGroup.call(d3.axisBottom(xScale).ticks(tickCount).tickFormat(d => (d / 1e6).toFixed(1)))
  }

  const xFontSize = chartCache.isNarrow ? '8px' : '10px'
  xAxisGroup.selectAll('text').attr('fill', '#666').style('font-size', xFontSize)
  xAxisGroup.selectAll('line').attr('stroke', '#666')
  xAxisGroup.select('.domain').attr('stroke', '#666')
}

// Redraw axis, vertical grid, and channel labels from current zoomed xScale
function updateAxisAndGrid() {
  if (!svgRef.value || !chartCache.xScale) return

  const svg = d3.select(svgRef.value)
  const { xScale, plotWidth, plotHeight, startHz, stopHz } = chartCache
  const startMHz = startHz / 1e6
  const stopMHz = stopHz / 1e6

  const atscChannels = getATSCChannels(startMHz, stopMHz)
  const wifi24Channels = getWifi24Channels(startMHz, stopMHz)
  const dectChannels = getDECTChannels(startMHz, stopMHz)
  const isUHF = atscChannels.length > 0
  const isWifi24 = wifi24Channels.length >= 3
  const isDECT = dectChannels.length >= 3

  drawVerticalGrid(svg.select('.v-grid'), xScale, plotHeight, startMHz, stopMHz, atscChannels, wifi24Channels, dectChannels, isUHF, isWifi24, isDECT)
  drawXAxis(svg.select('.x-axis'), svg.select('.channel-labels'), xScale, plotWidth, startMHz, stopMHz, atscChannels, wifi24Channels, dectChannels, isUHF, isWifi24, isDECT)
}

// Update just the trace paths (fast path)
function updateTraces() {
  if (!svgRef.value) return

  const svg = d3.select(svgRef.value)
  const tracesGroup = svg.select('.traces')
  const traces = getTracesForDraw()

  if (!chartCache.xScale || !chartCache.lineGenerator) return

  const { xScale, yScale, lineGenerator, plotWidth } = chartCache

  // Convert power to points, using visible range for smarter decimation
  function powerToPoints(power, hz_lo, hz_hi) {
    const points = []
    const len = power.length
    const hzPerSample = (hz_hi - hz_lo) / len

    // Determine visible frequency range from current (possibly zoomed) xScale
    const visibleLoHz = xScale.domain()[0]
    const visibleHiHz = xScale.domain()[1]

    // Clamp to data range
    const loHz = Math.max(hz_lo, visibleLoHz)
    const hiHz = Math.min(hz_hi, visibleHiHz)
    const iStart = Math.max(0, Math.floor((loHz - hz_lo) / hzPerSample))
    const iEnd = Math.min(len - 1, Math.ceil((hiHz - hz_lo) / hzPerSample))
    const visibleSamples = iEnd - iStart + 1

    // Downsample to pixel width. When more than one sample maps to a pixel
    // column we keep BOTH the min and max of that column (a min/max envelope)
    // rather than a single strided sample — otherwise a narrow peak that lands
    // between the sampled indices is dropped entirely and only reappears on
    // zoom. Max preserves signal peaks; min keeps the noise floor honest.
    const step = Math.max(1, Math.floor(visibleSamples / plotWidth))

    const pushPoint = (i) => {
      const freq = hz_lo + (i / len) * (hz_hi - hz_lo)
      const db = Math.max(minDb, Math.min(maxDb, power[i]))
      points.push({ x: xScale(freq), y: yScale(db) })
    }

    if (step === 1) {
      // One sample (or fewer) per pixel — draw them directly.
      for (let i = iStart; i <= iEnd; i++) pushPoint(i)
    } else {
      for (let i = iStart; i <= iEnd; i += step) {
        const binEnd = Math.min(i + step, iEnd + 1)
        let minI = i
        let maxI = i
        for (let j = i + 1; j < binEnd; j++) {
          if (power[j] < power[minI]) minI = j
          if (power[j] > power[maxI]) maxI = j
        }
        // Emit both extremes in ascending-frequency order so the polyline stays
        // monotonic in x and draws the column's full vertical extent.
        if (minI === maxI) {
          pushPoint(minI)
        } else if (minI < maxI) {
          pushPoint(minI)
          pushPoint(maxI)
        } else {
          pushPoint(maxI)
          pushPoint(minI)
        }
      }
    }
    return points
  }

  // D3 update pattern for traces (use sanitized ID for CSS class names)
  traces.forEach((trace) => {
    if (!trace.scan?.power?.length) return

    const { hz_lo, hz_hi, power } = trace.scan
    const traceId = trace.id
    const safeId = sanitizeClass(traceId)

    // Send to worker for peak/avg calculation
    // Use Array.from() to unwrap Vue reactive proxy — postMessage can't clone Proxy objects
    if (traceWorker && (props.showPeak || props.showAverage)) {
      traceWorker.postMessage({ type: 'update', traceId, power: Array.from(power) })
    }

    const workerData = workerResults[traceId]

    // Render order: peak (bottom) → average (middle) → current (top)
    // SVG draws later elements on top, so current/green is always visible

    // Peak trace - Red (rendered first, at bottom)
    if (props.showPeak && workerData?.peak) {
      const peakPoints = powerToPoints(workerData.peak, hz_lo, hz_hi)
      let peakPath = tracesGroup.select(`.trace-peak-${safeId}`)

      if (peakPath.empty()) {
        peakPath = tracesGroup.append('path')
          .attr('class', `trace-peak-${safeId}`)
          .attr('fill', 'none')
          .attr('stroke', '#ef4444')  // Red for peak
          .attr('stroke-width', 1)
          .attr('opacity', 0.8)
      }
      peakPath.datum(peakPoints).attr('d', lineGenerator)
    } else {
      tracesGroup.select(`.trace-peak-${safeId}`).remove()
    }

    // Average trace - Yellow (rendered second, middle)
    if (props.showAverage && workerData?.avg) {
      const avgPoints = powerToPoints(workerData.avg, hz_lo, hz_hi)
      let avgPath = tracesGroup.select(`.trace-avg-${safeId}`)

      if (avgPath.empty()) {
        avgPath = tracesGroup.append('path')
          .attr('class', `trace-avg-${safeId}`)
          .attr('fill', 'none')
          .attr('stroke', '#fbbf24')  // Yellow for average
          .attr('stroke-width', 1.5)
          .attr('stroke-dasharray', '4,2')
          .attr('opacity', 0.8)
      }
      avgPath.datum(avgPoints).attr('d', lineGenerator)
    } else {
      tracesGroup.select(`.trace-avg-${safeId}`).remove()
    }

    // Current trace - Green (rendered last, on top)
    // Live traces respect showCurrent toggle; explicit/historical traces always render
    const shouldShowTrace = trace.isLive ? props.showCurrent : true
    if (shouldShowTrace) {
      const currentPoints = powerToPoints(power, hz_lo, hz_hi)
      let currentPath = tracesGroup.select(`.trace-current-${safeId}`)

      if (currentPath.empty()) {
        currentPath = tracesGroup.append('path')
          .attr('class', `trace-current-${safeId}`)
          .attr('fill', 'none')
          .attr('stroke', trace.color)
          .attr('stroke-width', 1)
      }
      // Ensure current trace is on top by raising it
      currentPath.datum(currentPoints).attr('d', lineGenerator).raise()
    } else {
      tracesGroup.select(`.trace-current-${safeId}`).remove()
    }
  })

  // Remove stale trace paths from removed traces
  const activeClasses = new Set()
  for (const t of traces) {
    const sid = sanitizeClass(t.id)
    activeClasses.add(`trace-current-${sid}`)
    activeClasses.add(`trace-peak-${sid}`)
    activeClasses.add(`trace-avg-${sid}`)
  }
  tracesGroup.selectAll('path').each(function() {
    const cls = d3.select(this).attr('class')
    if (cls && cls.startsWith('trace-') && !activeClasses.has(cls)) {
      d3.select(this).remove()
    }
  })

  // Update legend only when trace set changes
  updateLegend(traces)
}

let lastLegendKey = ''

function updateLegend(traces) {
  // Build a key from trace IDs+names — skip rebuild if unchanged
  const key = traces.map(t => `${t.id}:${t.name}:${t.color}`).join('|')
  if (key === lastLegendKey) return
  lastLegendKey = key

  const svg = d3.select(svgRef.value)
  const legendGroup = svg.select('.legend')
  legendGroup.selectAll('*').remove()

  if (traces.length > 1) {
    traces.forEach((trace, idx) => {
      const legendItem = legendGroup.append('g')
        .attr('transform', `translate(0, ${idx * 18})`)
      legendItem.append('line')
        .attr('x1', -30).attr('y1', 0).attr('x2', -10).attr('y2', 0)
        .attr('stroke', trace.color).attr('stroke-width', 2)
      legendItem.append('text')
        .attr('x', -35).attr('y', 4).attr('text-anchor', 'end')
        .attr('fill', '#999').style('font-size', '10px').text(trace.name)
    })
  }
}

// Track the last frequency we emitted so we can avoid reacting to our own prop update
let lastEmittedCursorFreq = null

// Look up the power (dBm) at a given frequency from the first visible trace
function getPowerAtFreq(freqHz) {
  const trace = getTracesForDraw()[0]
  if (!trace?.scan?.power?.length) return null
  const { hz_lo, hz_hi, power } = trace.scan
  if (freqHz < hz_lo || freqHz > hz_hi) return null
  const idx = Math.round(((freqHz - hz_lo) / (hz_hi - hz_lo)) * (power.length - 1))
  if (idx < 0 || idx >= power.length) return null
  return power[idx]
}

function setupMouseHandlers() {
  const svg = d3.select(svgRef.value)
  const mouseOverlay = svg.select('.mouse-overlay')
  const cursorLineV = svg.select('.cursor-line-v')
  const cursorLineH = svg.select('.cursor-line-h')
  const cursorDot = svg.select('.cursor-dot')

  function clearCursor() {
    cursorLineV.attr('opacity', 0)
    cursorLineH.attr('opacity', 0)
    cursorDot.attr('opacity', 0)
    cursorInfo.value = null
    lastEmittedCursorFreq = null
    emit('cursor-move', null)
  }

  function showCrosshair(mx, freqHz) {
    const freqMHz = freqHz / 1e6
    const powerDbm = getPowerAtFreq(freqHz)
    lastEmittedCursorFreq = freqHz
    emit('cursor-move', freqHz)

    // Check if cursor is near a selected server pin (within 8px)
    let nearPin = null
    for (const pin of props.pinnedFreqs) {
      if (!pin.isServer || !pin.selected) continue
      const pinX = chartCache.xScale(pin.freqHz)
      if (Math.abs(mx - pinX) <= 8) {
        const pinPower = getPowerAtFreq(pin.freqHz)
        nearPin = {
          name: pin.name,
          category: pin.category,
          notes: pin.notes,
          color: pin.color,
          freqMHz: pin.freqMHz.toFixed(3),
          powerDbm: pinPower !== null ? pinPower.toFixed(1) : null,
        }
        break
      }
    }

    cursorLineV.attr('x1', mx).attr('x2', mx).attr('opacity', 0.6)
    if (powerDbm !== null) {
      const powerY = chartCache.yScale(powerDbm)
      cursorLineH.attr('y1', powerY).attr('y2', powerY).attr('opacity', 0.6)
      cursorDot.attr('cx', mx).attr('cy', powerY).attr('opacity', 1)
      cursorInfo.value = {
        x: mx + chartCache.margin.left,
        y: powerY + chartCache.margin.top,
        freqMHz: freqMHz.toFixed(3),
        powerDbm: powerDbm.toFixed(1),
        pin: nearPin,
      }
    }
  }

  // Attach cursor/click/touch handlers to the brush overlay (topmost element)
  // so they work even with the brush layer on top of mouse-overlay
  const brushOverlayEl = svg.select('.brush .overlay')
  const eventTarget = brushOverlayEl.empty() ? mouseOverlay : brushOverlayEl

  eventTarget
    .on('mousemove', (event) => {
      const [mx] = d3.pointer(event)
      showCrosshair(mx, chartCache.xScale.invert(mx))
    })
    .on('mouseleave', clearCursor)
    .on('click', (event) => {
      if (event.metaKey || event.ctrlKey) {
        const [mx] = d3.pointer(event)
        const freqHz = chartCache.xScale.invert(mx)
        emit('freq-pin', { freqHz, freqMHz: freqHz / 1e6 })
      }
    })

  // Long-press + drag-to-refine for touch frequency pinning
  let longPressTimer = null
  let longPressX = null
  let longPressActive = false
  let lastPinX = null

  function showPinCursor(mx) {
    const clampedX = Math.max(0, Math.min(chartCache.plotWidth, mx))
    const freqHz = chartCache.xScale.invert(clampedX)
    const powerDbm = getPowerAtFreq(freqHz)
    lastPinX = clampedX

    cursorLineV.attr('x1', clampedX).attr('x2', clampedX)
      .attr('opacity', 1).attr('stroke', '#00d4ff').attr('stroke-width', 2)
      .attr('stroke-dasharray', null)
    cursorLineH.attr('opacity', 0)
    cursorDot.attr('opacity', 0)
    cursorInfo.value = {
      x: clampedX + chartCache.margin.left,
      y: chartCache.margin.top + 20,
      freqMHz: (freqHz / 1e6).toFixed(3),
      powerDbm: powerDbm !== null ? powerDbm.toFixed(1) : null,
      pinMode: true,
    }
    lastEmittedCursorFreq = freqHz
    emit('cursor-move', freqHz)
  }

  eventTarget
    .on('touchstart.longpress', (event) => {
      if (event.touches.length !== 1) return
      const [mx] = d3.pointer(event.touches[0], eventTarget.node())
      longPressX = mx
      longPressActive = false
      lastPinX = null
      longPressTimer = setTimeout(() => {
        if (longPressX === null || !chartCache.xScale) return
        longPressActive = true
        if (navigator.vibrate) navigator.vibrate(30)
        showPinCursor(longPressX)
      }, 400)
    })
    .on('touchmove.longpress', (event) => {
      if (longPressX === null) return
      const [mx] = d3.pointer(event.touches[0], eventTarget.node())
      if (longPressActive) {
        event.preventDefault()
        showPinCursor(mx)
      } else if (Math.abs(mx - longPressX) > 10) {
        clearTimeout(longPressTimer)
        longPressX = null
      }
    })
    .on('touchend.longpress touchcancel.longpress', () => {
      clearTimeout(longPressTimer)
      if (longPressActive && lastPinX !== null && chartCache.xScale) {
        const freqHz = chartCache.xScale.invert(lastPinX)
        emit('freq-pin', { freqHz, freqMHz: freqHz / 1e6 })
      }
      longPressActive = false
      longPressX = null
      lastPinX = null
      clearCursor()
    })
}

// Main draw function
function draw() {
  buildChartStructure()
  updateTraces()
  drawCategoryBands()
  drawPinnedMarkers()
}

// Resize handling
let resizeObserver = null

function setupResizeObserver() {
  if (container.value) {
    resizeObserver = new ResizeObserver(() => {
      // Force rebuild on resize
      chartCache.width = 0
      draw()
    })
    resizeObserver.observe(container.value)
  }
}

// Event bus handler
function handleRedrawSignal(bandName) {
  if (bandName === props.bandName && props.getScanData) {
    currentScanData = props.getScanData(bandName)
    updateTraces()  // Fast path - just update traces
  }
}

let unsubscribeBus = null

// Watch for display mode changes
watch(() => [props.showCurrent, props.showAverage, props.showPeak], () => {
  // Refresh scan data when toggling display modes (especially when going back to live)
  if (props.getScanData && props.bandName && props.showCurrent) {
    currentScanData = props.getScanData(props.bandName)
  }
  updateTraces()
})

// Watch for prop changes — traces array is replaced by reference in BandChart computed,
// so shallow watch catches all meaningful changes without expensive deep comparison
watch(() => [props.scan, props.traces], () => {
  // draw() will rebuild chart structure only if frequency range actually changed,
  // otherwise just updateTraces() runs — preserving zoom state
  draw()
})

// External cursor from another chart (e.g. spectrogram)
// External cursor from another chart — show native crosshair
watch(() => props.cursorFreq, (freqHz) => {
  if (!svgRef.value || !chartCache.xScale) return
  const svg = d3.select(svgRef.value)
  const cursorLineV = svg.select('.cursor-line-v')
  const cursorLineH = svg.select('.cursor-line-h')
  const cursorDot = svg.select('.cursor-dot')

  // Ignore if this is our own emitted value bouncing back
  if (freqHz !== null && freqHz === lastEmittedCursorFreq) return

  if (freqHz === null) {
    cursorLineV.attr('opacity', 0)
    cursorLineH.attr('opacity', 0)
    cursorDot.attr('opacity', 0)
    cursorInfo.value = null
    return
  }

  const mx = chartCache.xScale(freqHz)
  if (mx >= 0 && mx <= chartCache.plotWidth) {
    const powerDbm = getPowerAtFreq(freqHz)
    cursorLineV.attr('x1', mx).attr('x2', mx).attr('opacity', 0.6)
      .attr('stroke', '#666').attr('stroke-width', 1).attr('stroke-dasharray', '4,4')
    if (powerDbm !== null) {
      const powerY = chartCache.yScale(powerDbm)
      cursorLineH.attr('y1', powerY).attr('y2', powerY).attr('opacity', 0.6)
      cursorDot.attr('cx', mx).attr('cy', powerY).attr('opacity', 1)
      cursorInfo.value = {
        x: mx + chartCache.margin.left,
        y: powerY + chartCache.margin.top,
        freqMHz: (freqHz / 1e6).toFixed(3),
        powerDbm: powerDbm.toFixed(1),
      }
    } else {
      cursorLineH.attr('opacity', 0)
      cursorDot.attr('opacity', 0)
      cursorInfo.value = null
    }
  } else {
    cursorLineV.attr('opacity', 0)
    cursorLineH.attr('opacity', 0)
    cursorDot.attr('opacity', 0)
    cursorInfo.value = null
  }
})

// Draw pinned frequency markers and category bands
watch(() => props.pinnedFreqs, () => {
  drawCategoryBands()
  drawPinnedMarkers()
})

function drawCategoryBands() {
  if (!svgRef.value || !chartCache.xScale) return
  const svg = d3.select(svgRef.value)
  const group = svg.select('.category-bands')
  if (group.empty()) return
  group.selectAll('*').remove()

  const { xScale, plotHeight, plotWidth } = chartCache

  // Group selected server pins by category
  const categories = {}
  for (const pin of props.pinnedFreqs) {
    if (!pin.isServer || !pin.category || !pin.selected) continue
    const x = xScale(pin.freqHz)
    if (x < 0 || x > plotWidth) continue
    if (!categories[pin.category]) {
      categories[pin.category] = { pins: [], color: pin.color }
    }
    categories[pin.category].pins.push({ x, freqHz: pin.freqHz })
  }

  // Draw bands for categories with 2+ visible frequencies
  for (const [catName, cat] of Object.entries(categories)) {
    if (cat.pins.length < 2) continue
    const xs = cat.pins.map(p => p.x)
    const minX = Math.min(...xs)
    const maxX = Math.max(...xs)

    group.append('rect')
      .attr('x', minX)
      .attr('y', 0)
      .attr('width', maxX - minX)
      .attr('height', plotHeight)
      .attr('fill', cat.color)
      .attr('opacity', 0.06)

    // Category name centered at bottom
    const centerX = (minX + maxX) / 2
    if (centerX > 0 && centerX < plotWidth) {
      group.append('text')
        .attr('x', centerX)
        .attr('y', plotHeight - 4)
        .attr('text-anchor', 'middle')
        .attr('fill', cat.color)
        .attr('font-size', '9px')
        .attr('opacity', 0.4)
        .text(catName)
    }
  }
}

function drawPinnedMarkers() {
  if (!svgRef.value || !chartCache.xScale) return
  const svg = d3.select(svgRef.value)
  let group = svg.select('.pinned-markers')
  if (group.empty()) {
    group = svg.select('.traces').append('g').attr('class', 'pinned-markers')
  }

  const { xScale, plotHeight, plotWidth } = chartCache

  // Phase 1: Collect visible server pins sorted by x-position for label staggering
  const visibleServerPins = []
  for (const pin of props.pinnedFreqs) {
    const x = xScale(pin.freqHz)
    if (x < 0 || x > plotWidth) continue
    if (pin.isServer) {
      const powerDbm = getPowerAtFreq(pin.freqHz)
      const alert = pin.selected && powerDbm !== null && powerDbm > INTERFERENCE_THRESHOLD_DBM
      visibleServerPins.push({ ...pin, x, powerDbm, alert })
    }
  }
  visibleServerPins.sort((a, b) => a.x - b.x)

  // Phase 2: Assign tiers to stagger overlapping selected labels
  let prevX = -Infinity
  let tier = 0
  for (const sp of visibleServerPins) {
    if (!sp.selected) continue
    if (sp.x - prevX < 50) {
      tier = (tier + 1) % 3
    } else {
      tier = 0
    }
    sp.tier = tier
    prevX = sp.x
  }

  // Phase 3: Server pins — D3 join to avoid destroy/recreate on every scan
  // Each pin gets a group containing its line + optional name + optional power text
  const pinGroups = group.selectAll('.pin-group')
    .data(visibleServerPins, d => d.freqHz)
    .join(
      enter => {
        const g = enter.append('g').attr('class', 'pin-group')
        g.append('line').attr('class', 'pin-line')
        g.append('text').attr('class', 'pin-name')
        g.append('text').attr('class', 'pin-power')
          .attr('font-size', '9px')
          .attr('font-family', 'monospace')
          .attr('opacity', 0.85)
        return g
      }
    )

  // Update all pin groups (enter + update)
  pinGroups.each(function(sp) {
    const g = d3.select(this)

    if (!sp.selected) {
      // Unselected: subtle line, hide labels
      g.select('.pin-line')
        .attr('x1', sp.x).attr('y1', 0)
        .attr('x2', sp.x).attr('y2', plotHeight)
        .attr('stroke', sp.color)
        .attr('stroke-width', 0.5)
        .attr('opacity', 0.15)
      g.select('.pin-name').attr('opacity', 0)
      g.select('.pin-power').attr('opacity', 0)
      return
    }

    // Selected: full styling
    const lineColor = sp.alert ? '#ef4444' : sp.color
    const lineWidth = sp.alert ? 2 : 1.5

    g.select('.pin-line')
      .attr('x1', sp.x).attr('y1', 0)
      .attr('x2', sp.x).attr('y2', plotHeight)
      .attr('stroke', lineColor)
      .attr('stroke-width', lineWidth)
      .attr('opacity', 0.8)

    const labelY = 12 + (sp.tier || 0) * 14
    const nearRightEdge = sp.x > plotWidth - 60
    const anchor = nearRightEdge ? 'end' : 'start'
    const xOffset = nearRightEdge ? -4 : 4

    // Name label — only update text if alert state changed
    g.select('.pin-name')
      .attr('x', sp.x + xOffset)
      .attr('y', labelY)
      .attr('text-anchor', anchor)
      .attr('fill', sp.alert ? '#ef4444' : sp.color)
      .attr('font-size', '10px')
      .attr('font-weight', '600')
      .attr('opacity', sp.name ? 0.9 : 0)
      .text(sp.name ? (sp.alert ? '\u26a0 ' + sp.name : sp.name) : '')

    // Power readout — this is the only value that changes per scan
    g.select('.pin-power')
      .attr('x', sp.x + xOffset)
      .attr('y', labelY + 11)
      .attr('text-anchor', anchor)
      .attr('fill', sp.alert ? '#ef4444' : '#9ca3af')
      .attr('font-weight', sp.alert ? 'bold' : 'normal')
      .attr('opacity', sp.powerDbm !== null ? 0.85 : 0)
      .text(sp.powerDbm !== null ? sp.powerDbm.toFixed(1) : '')
  })

  // Phase 4: Ad-hoc pins — same join pattern
  const adHocPins = props.pinnedFreqs
    .filter(p => !p.isServer)
    .map(p => ({ ...p, x: xScale(p.freqHz) }))
    .filter(p => p.x >= 0 && p.x <= plotWidth)

  group.selectAll('.adhoc-pin')
    .data(adHocPins, d => d.freqHz)
    .join(
      enter => enter.append('line')
        .attr('class', 'adhoc-pin')
        .attr('stroke-dasharray', '4,2')
        .attr('opacity', 0.7)
    )
    .attr('x1', d => d.x).attr('y1', 0)
    .attr('x2', d => d.x).attr('y2', plotHeight)
    .attr('stroke', d => d.color)
    .attr('stroke-width', 1)
}

onMounted(() => {
  initWorker()
  setupResizeObserver()

  if (props.scanBus && props.bandName) {
    unsubscribeBus = props.scanBus.on(handleRedrawSignal)
    if (props.getScanData) {
      currentScanData = props.getScanData(props.bandName)
    }
  }

  draw()
})

onUnmounted(() => {
  if (resizeObserver) resizeObserver.disconnect()
  if (unsubscribeBus) unsubscribeBus()
  if (traceWorker) traceWorker.terminate()
})

// Expose reset functions
function resetPeak(traceId) {
  if (traceWorker) {
    traceWorker.postMessage({ type: 'resetPeak', traceId })
  }
  if (workerResults[traceId]) {
    delete workerResults[traceId].peak
  }
}

// Get the element that owns the zoom transform (brush overlay if present, else mouse overlay)
function getZoomElement() {
  const svg = d3.select(svgRef.value)
  const brushOvl = svg.select('.brush .overlay')
  return brushOvl.empty() ? svg.select('.mouse-overlay') : brushOvl
}

function resetZoom() {
  if (!svgRef.value || !chartCache.zoomBehavior) return
  // Instant, matching setZoom — this is the spectrogram-driven reset, and the
  // waterfall snaps to full band immediately, so the two must reset together.
  getZoomElement()
    .call(chartCache.zoomBehavior.transform, d3.zoomIdentity)
}

// Programmatically set zoom to a given frequency domain [loHz, hiHz]
// Used by parent to sync zoom from the spectrogram. Applied instantly (no transition):
// the spectrogram jumps straight to the new window, so an eased animation here would
// just lag the waterfall during a continuous pan and read as the two charts drifting
// apart. Instant keeps them locked together.
function setZoom(domain) {
  if (!svgRef.value || !chartCache.zoomBehavior || !chartCache.xScaleBase) return
  const [loHz, hiHz] = domain
  const { xScaleBase, zoomBehavior, startHz, stopHz } = chartCache
  const k = (stopHz - startHz) / (hiHz - loHz)
  const tx = -xScaleBase(loHz) * k
  getZoomElement()
    .call(zoomBehavior.transform, d3.zoomIdentity.translate(tx, 0).scale(k))
}

defineExpose({
  resetPeak,
  resetAllPeaks: () => {
    Object.keys(workerResults).forEach(id => resetPeak(id))
  },
  resetZoom,
  setZoom,
})
</script>

<template>
  <div ref="container" class="d3-spectrum-chart w-full relative">
    <svg ref="svgRef" class="w-full rounded" :style="{ height: `${height}px` }"></svg>

    <div
      v-if="cursorInfo"
      class="absolute pointer-events-none rounded px-2 py-1 text-xs"
      :class="cursorInfo.pinMode
        ? 'bg-cyan-900/95 border border-cyan-400/70'
        : 'bg-gray-900/90 border border-cyan-500/50'"
      :style="{
        left: `${cursorInfo.x + 10}px`,
        top: `${cursorInfo.pin ? cursorInfo.y - 70 : cursorInfo.y - 30}px`,
      }"
    >
      <!-- Pin tooltip (when hovering near a server pin) -->
      <template v-if="cursorInfo.pin">
        <div class="font-semibold mb-0.5" :style="{ color: cursorInfo.pin.color }">{{ cursorInfo.pin.name }}</div>
        <div v-if="cursorInfo.pin.category" class="text-gray-400">{{ cursorInfo.pin.category }}</div>
        <div class="text-cyan-400 font-mono">{{ cursorInfo.pin.freqMHz }} MHz</div>
        <div v-if="cursorInfo.pin.powerDbm != null" class="text-yellow-400 font-mono">{{ cursorInfo.pin.powerDbm }} dBm</div>
        <div v-if="cursorInfo.pin.notes" class="text-gray-500 mt-0.5 max-w-[180px] truncate">{{ cursorInfo.pin.notes }}</div>
      </template>
      <!-- Standard tooltip -->
      <template v-else>
        <div v-if="cursorInfo.pinMode" class="text-cyan-300 font-semibold mb-0.5">Pin frequency</div>
        <div class="text-cyan-400 font-mono">{{ cursorInfo.freqMHz }} MHz</div>
        <div v-if="cursorInfo.powerDbm != null" class="text-yellow-400 font-mono">{{ cursorInfo.powerDbm }} dBm</div>
      </template>
    </div>
  </div>
</template>

<style scoped>
.d3-spectrum-chart {
  position: relative;
  touch-action: manipulation;
  -webkit-touch-callout: none;
  -webkit-user-select: none;
  user-select: none;
}
</style>
