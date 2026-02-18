<script setup>
import { ref, watch, onMounted, onUnmounted, computed, nextTick } from 'vue'
import * as d3 from 'd3'

const props = defineProps({
  band: {
    type: Object,
    default: null,
  },
  height: {
    type: Number,
    default: 200,
  },
  scan: {
    type: Object,
    default: null,
  },
  historicalScans: {
    type: Array,
    default: () => [],
  },
  isLive: {
    type: Boolean,
    default: true,
  },
  // Visible frequency range from line chart zoom [loHz, hiHz]
  visibleRange: {
    type: Array,
    default: null,
  },
  // External cursor frequency (Hz) from another chart
  cursorFreq: {
    type: Number,
    default: null,
  },
  // Timestamp of currently displayed scan (for highlight row)
  highlightTime: {
    type: Number,
    default: null,
  },
  // Pinned frequencies for time-series: [{ freqHz, freqMHz, color }]
  pinnedFreqs: {
    type: Array,
    default: () => [],
  },
})

const emit = defineEmits(['cursor-move', 'select', 'freq-pin'])

const container = ref(null)
const canvasRef = ref(null)
const svgRef = ref(null)
const legendCanvas = ref(null)

// dBm range for color mapping
const minDb = -110
const maxDb = -20
const dbRange = maxDb - minDb

// Match D3SpectrumChart left/right margins for x-axis alignment. No own x-axis.
const margin = { top: 2, right: 50, bottom: 2, left: 55 }

// Scan buffer: index 0 = oldest (top), index N-1 = newest (bottom)
const scanBuffer = ref([])

// Viridis colormap - 256 entries as both Uint8Array (for legend) and Uint32Array (for fast pixel writes)
const { VIRIDIS_U8, VIRIDIS_U32 } = buildViridis()

function buildViridis() {
  const colors = [
    [68,1,84],[68,2,86],[69,4,87],[69,5,89],[70,7,90],[70,8,92],[70,10,93],[70,11,94],
    [71,13,96],[71,14,97],[71,16,99],[71,17,100],[71,19,101],[72,20,103],[72,22,104],[72,23,105],
    [72,24,106],[72,26,108],[72,27,109],[72,28,110],[72,29,111],[72,31,112],[72,32,113],[72,33,115],
    [72,35,116],[72,36,117],[72,37,118],[72,38,119],[72,40,120],[72,41,121],[71,42,122],[71,44,122],
    [71,45,123],[71,46,124],[71,47,125],[70,48,126],[70,50,126],[70,51,127],[69,52,128],[69,53,129],
    [69,55,129],[68,56,130],[68,57,131],[67,58,131],[67,60,132],[66,61,132],[66,62,133],[65,63,133],
    [65,64,134],[64,66,134],[63,67,134],[63,68,135],[62,69,135],[61,71,135],[61,72,136],[60,73,136],
    [59,74,136],[58,75,136],[58,76,137],[57,77,137],[56,78,137],[56,79,137],[55,80,137],[54,81,137],
    [53,82,138],[53,83,138],[52,84,138],[51,85,138],[50,86,138],[50,87,138],[49,88,138],[48,89,138],
    [47,90,138],[46,91,138],[46,92,138],[45,93,138],[44,94,138],[43,95,138],[42,96,138],[42,97,137],
    [41,98,137],[40,99,137],[39,100,137],[39,101,137],[38,102,137],[37,103,136],[36,104,136],[35,105,136],
    [35,106,136],[34,107,135],[33,108,135],[32,109,135],[32,110,134],[31,111,134],[30,112,134],[30,113,133],
    [29,114,133],[28,115,132],[28,116,132],[27,117,131],[27,118,131],[26,119,130],[26,120,130],[25,121,129],
    [25,122,129],[24,123,128],[24,124,127],[24,125,127],[23,126,126],[23,127,125],[23,128,125],[23,129,124],
    [23,130,123],[23,131,122],[23,132,122],[23,133,121],[23,134,120],[23,134,119],[24,135,118],[24,136,118],
    [24,137,117],[25,138,116],[25,139,115],[26,140,114],[26,141,113],[27,141,112],[28,142,111],[29,143,110],
    [29,144,109],[30,144,108],[31,145,107],[32,146,106],[33,146,105],[34,147,104],[36,148,103],[37,148,102],
    [38,149,101],[40,150,100],[41,150,99],[42,151,97],[44,151,96],[45,152,95],[47,152,94],[49,153,93],
    [50,153,92],[52,154,90],[53,154,89],[55,155,88],[57,155,87],[59,156,85],[61,156,84],[62,157,83],
    [64,157,82],[66,157,80],[68,158,79],[70,158,78],[72,159,76],[74,159,75],[76,159,74],[78,160,73],
    [80,160,71],[82,161,70],[84,161,69],[86,161,67],[88,161,66],[90,162,65],[92,162,63],[94,162,62],
    [96,162,61],[98,163,59],[100,163,58],[102,163,57],[104,163,55],[106,163,54],[108,164,53],[110,164,51],
    [112,164,50],[114,164,49],[116,164,47],[118,164,46],[120,164,45],[122,164,43],[124,165,42],[126,165,41],
    [128,165,39],[130,165,38],[132,165,37],[134,165,36],[136,165,34],[138,165,33],[140,165,32],[142,165,31],
    [144,165,30],[146,165,29],[148,165,28],[150,165,27],[152,165,26],[154,164,26],[155,164,25],[157,164,24],
    [159,164,24],[161,163,24],[163,163,23],[165,163,23],[167,162,23],[168,162,23],[170,161,23],[172,161,24],
    [174,160,24],[176,160,24],[177,159,25],[179,158,25],[181,158,26],[183,157,27],[184,156,27],[186,156,28],
    [188,155,29],[189,154,30],[191,153,31],[193,153,32],[194,152,33],[196,151,34],[197,150,35],[199,149,36],
    [200,149,37],[202,148,38],[203,147,39],[205,146,41],[206,145,42],[207,144,43],[209,143,44],[210,142,46],
    [211,141,47],[213,140,48],[214,139,50],[215,138,51],[217,137,53],[218,136,54],[219,135,55],[220,134,57],
    [221,133,58],[222,132,60],[223,130,62],[224,129,63],[225,128,65],[226,127,66],[227,126,68],[228,125,69],
    [229,124,71],[230,122,73],[230,121,74],[231,120,76],[232,119,78],[233,118,79],[234,116,81],[235,115,83],
    [235,114,84],[236,113,86],[237,112,88],[237,110,90],[238,109,91],[238,108,93],[239,107,95],[239,105,97],
    [240,104,99],[240,103,100],[241,102,102],[241,100,104],[242,99,106],[242,98,108],[242,96,110],[243,95,111],
    [243,94,113],[243,92,115],[244,91,117],[244,90,119],[244,88,121],[244,87,123],[245,86,125],[245,84,126],
    [245,83,128],[245,82,130],[246,80,132],[246,79,134],[246,78,136],[246,76,138],[246,75,140],[247,73,141],
    [247,72,143],[247,71,145],[247,69,147],[247,68,149],[247,66,151],[247,65,153],[247,64,155],[248,62,156],
    [248,61,158],[248,59,160],[248,58,162],[248,56,164],[248,55,166],[248,54,168],[248,52,170],[248,51,171],
    [248,49,173],[248,48,175],[249,46,177],[249,45,179],[249,43,181],[249,42,183],[249,40,185],[249,39,186],
  ]
  // Uint8Array for legend rendering
  const lut = new Uint8Array(256 * 4)
  // Uint32Array for fast single-write pixel fills (ABGR on little-endian)
  const lut32 = new Uint32Array(256)
  for (let i = 0; i < 256; i++) {
    const c = colors[Math.min(i, colors.length - 1)]
    lut[i * 4] = c[0]
    lut[i * 4 + 1] = c[1]
    lut[i * 4 + 2] = c[2]
    lut[i * 4 + 3] = 255
    // ABGR byte order for Uint32 on little-endian systems
    lut32[i] = (255 << 24) | (c[2] << 16) | (c[1] << 8) | c[0]
  }
  return { VIRIDIS_U8: lut, VIRIDIS_U32: lut32 }
}

function dbmToIndex(dbm) {
  const clamped = Math.max(minDb, Math.min(maxDb, dbm))
  return Math.round(((clamped - minDb) / dbRange) * 255)
}

// Chart dimensions
let plotWidth = 0
let plotHeight = 0
let canvasWidth = 0
let canvasHeight = 0

// Full band frequency range (from band prop)
let startHz = 0
let stopHz = 0

let ctx = null
let effectiveXScale = null

const cursorInfo = ref(null)

// Effective frequency range (zoomed or full band)
function getEffectiveRange() {
  if (props.visibleRange) return props.visibleRange
  return [startHz, stopHz]
}

// Full redraw of the waterfall from buffer (used for historical load, zoom, resize)
function renderWaterfall() {
  if (!ctx || canvasWidth === 0 || canvasHeight === 0) return

  const buf = scanBuffer.value
  if (buf.length === 0) {
    ctx.clearRect(0, 0, canvasWidth, canvasHeight)
    return
  }

  const [renderStartHz, renderStopHz] = getEffectiveRange()
  if (renderStopHz <= renderStartHz) return
  const hzPerPixel = (renderStopHz - renderStartHz) / canvasWidth

  const imgData = ctx.createImageData(canvasWidth, canvasHeight)
  const pixels32 = new Uint32Array(imgData.data.buffer)

  const oldestTs = buf[0].timestamp
  const newestTs = buf[buf.length - 1].timestamp
  const timeSpan = newestTs - oldestTs || 1

  let searchIdx = 0
  for (let row = 0; row < canvasHeight; row++) {
    const rowTime = oldestTs + (row / (canvasHeight - 1 || 1)) * timeSpan

    while (searchIdx < buf.length - 1 && buf[searchIdx + 1].timestamp <= rowTime) {
      searchIdx++
    }

    if (rowTime - buf[searchIdx].timestamp > 120000) continue

    const scan = buf[searchIdx]
    const power = scan.power
    const scanHzLo = scan.hz_lo
    const scanHzHi = scan.hz_hi
    const scanLen = power.length
    const scanHzPerSample = (scanHzHi - scanHzLo) / scanLen
    const rowOffset = row * canvasWidth

    for (let col = 0; col < canvasWidth; col++) {
      const freqHz = renderStartHz + col * hzPerPixel
      const sampleIdx = (freqHz - scanHzLo) / scanHzPerSample
      let dbm
      if (sampleIdx < 0 || sampleIdx >= scanLen) {
        dbm = minDb
      } else {
        dbm = power[Math.round(sampleIdx)]
      }
      pixels32[rowOffset + col] = VIRIDIS_U32[dbmToIndex(dbm)]
    }
  }

  ctx.putImageData(imgData, 0, 0)
}

// Fast path: shift canvas up by 1 row, paint only the newest scan at the bottom
function renderLiveRow(scan) {
  if (!ctx || canvasWidth === 0 || canvasHeight === 0) return
  if (!scan?.power?.length) return

  const [renderStartHz, renderStopHz] = getEffectiveRange()
  if (renderStopHz <= renderStartHz) return
  const hzPerPixel = (renderStopHz - renderStartHz) / canvasWidth

  // Shift existing content up by 1 row
  const existing = ctx.getImageData(0, 1, canvasWidth, canvasHeight - 1)
  ctx.putImageData(existing, 0, 0)

  // Paint the new row at the bottom
  const rowData = ctx.createImageData(canvasWidth, 1)
  const rowPixels32 = new Uint32Array(rowData.data.buffer)

  const power = scan.power
  const scanHzLo = scan.hz_lo
  const scanHzHi = scan.hz_hi
  const scanLen = power.length
  const scanHzPerSample = (scanHzHi - scanHzLo) / scanLen

  for (let col = 0; col < canvasWidth; col++) {
    const freqHz = renderStartHz + col * hzPerPixel
    const sampleIdx = (freqHz - scanHzLo) / scanHzPerSample
    let dbm
    if (sampleIdx < 0 || sampleIdx >= scanLen) {
      dbm = minDb
    } else {
      dbm = power[Math.round(sampleIdx)]
    }
    rowPixels32[col] = VIRIDIS_U32[dbmToIndex(dbm)]
  }

  ctx.putImageData(rowData, 0, canvasHeight - 1)
}

// Render the color legend gradient
function renderLegend() {
  if (!legendCanvas.value) return
  const lctx = legendCanvas.value.getContext('2d')
  const h = legendCanvas.value.height
  const w = legendCanvas.value.width
  if (h === 0 || w === 0) return

  const imgData = lctx.createImageData(w, h)
  for (let y = 0; y < h; y++) {
    const ci = Math.round((1 - y / h) * 255)
    for (let x = 0; x < w; x++) {
      const px = (y * w + x) * 4
      imgData.data[px] = VIRIDIS_U8[ci * 4]
      imgData.data[px + 1] = VIRIDIS_U8[ci * 4 + 1]
      imgData.data[px + 2] = VIRIDIS_U8[ci * 4 + 2]
      imgData.data[px + 3] = 255
    }
  }
  lctx.putImageData(imgData, 0, 0)
}

// Build SVG overlay (time axis + cursor only, no frequency axis)
function buildAxes() {
  if (!svgRef.value || !container.value) return

  const rect = container.value.getBoundingClientRect()
  const totalWidth = rect.width
  const totalHeight = props.height

  plotWidth = totalWidth - margin.left - margin.right
  plotHeight = totalHeight - margin.top - margin.bottom
  canvasWidth = Math.max(1, Math.floor(plotWidth))
  canvasHeight = Math.max(1, Math.floor(plotHeight))

  if (props.band) {
    startHz = props.band.start_hz
    stopHz = props.band.stop_hz
  } else {
    startHz = 470e6
    stopHz = 608e6
  }

  // Effective x scale (respects zoom from line chart)
  const [renderStartHz, renderStopHz] = getEffectiveRange()
  effectiveXScale = d3.scaleLinear()
    .domain([renderStartHz, renderStopHz])
    .range([0, plotWidth])

  // Size canvas to plot area
  if (canvasRef.value) {
    canvasRef.value.width = canvasWidth
    canvasRef.value.height = canvasHeight
    canvasRef.value.style.width = canvasWidth + 'px'
    canvasRef.value.style.height = canvasHeight + 'px'
    canvasRef.value.style.left = margin.left + 'px'
    canvasRef.value.style.top = margin.top + 'px'
    ctx = canvasRef.value.getContext('2d')
  }

  const svg = d3.select(svgRef.value)
  svg.selectAll('*').remove()
  svg.attr('width', totalWidth).attr('height', totalHeight)

  const chart = svg.append('g')
    .attr('transform', `translate(${margin.left},${margin.top})`)

  // Y-axis (time) on left side
  const yAxisGroup = chart.append('g').attr('class', 'y-axis')
  updateTimeAxis(yAxisGroup)

  // Cursor line
  const cursorGroup = chart.append('g').attr('class', 'cursor-overlay')
  cursorGroup.append('line').attr('class', 'cursor-line')
    .attr('y1', 0).attr('y2', plotHeight)
    .attr('stroke', '#666').attr('stroke-width', 1)
    .attr('stroke-dasharray', '4,4').attr('opacity', 0)

  // Overlays group for highlight row and pinned markers (below mouse overlay)
  chart.append('g').attr('class', 'chart-overlays')

  // Mouse overlay for cursor
  chart.append('rect').attr('class', 'mouse-overlay')
    .attr('width', plotWidth).attr('height', plotHeight)
    .attr('fill', 'transparent').attr('pointer-events', 'all')

  setupMouseHandlers()
}

function updateTimeAxis(yAxisGroup) {
  if (!yAxisGroup) {
    const svg = d3.select(svgRef.value)
    yAxisGroup = svg.select('.y-axis')
  }
  if (yAxisGroup.empty()) return

  yAxisGroup.selectAll('*').remove()

  const buf = scanBuffer.value
  if (buf.length < 2) return

  // Flow up: buf[0] = oldest (top), buf[N-1] = newest (bottom)
  const oldestTs = buf[0]?.timestamp || Date.now()
  const newestTs = buf[buf.length - 1]?.timestamp || Date.now()

  const tickCount = Math.min(5, Math.max(2, Math.floor(plotHeight / 40)))

  if (props.isLive) {
    const spanSec = (newestTs - oldestTs) / 1000
    const yScale = d3.scaleLinear()
      .domain([-spanSec, 0]) // past at top, "Now" at bottom
      .range([0, plotHeight])

    yAxisGroup.call(
      d3.axisLeft(yScale)
        .ticks(tickCount)
        .tickFormat(d => {
          if (d === 0) return 'Now'
          return `${d.toFixed(0)}s`
        })
    )
  } else {
    const yScale = d3.scaleTime()
      .domain([new Date(oldestTs), new Date(newestTs)])
      .range([0, plotHeight])

    yAxisGroup.call(
      d3.axisLeft(yScale)
        .ticks(tickCount)
        .tickFormat(d3.timeFormat('%H:%M:%S'))
    )
  }

  yAxisGroup.selectAll('text').attr('fill', '#666').style('font-size', '9px')
  yAxisGroup.selectAll('line').attr('stroke', '#666')
  yAxisGroup.select('.domain').attr('stroke', '#666')
}

// Track the last frequency we emitted so we can avoid reacting to our own prop update
let lastEmittedCursorFreq = null

function setupMouseHandlers() {
  const svg = d3.select(svgRef.value)
  const mouseOverlay = svg.select('.mouse-overlay')
  const cursorLine = svg.select('.cursor-line')

  mouseOverlay
    .on('mousemove', (event) => {
      if (!effectiveXScale) return
      const [mx] = d3.pointer(event)
      const freqHz = effectiveXScale.invert(mx)
      const freqMHz = freqHz / 1e6

      cursorLine.attr('x1', mx).attr('x2', mx).attr('opacity', 0.6)
      cursorInfo.value = {
        x: mx + margin.left,
        freqMHz: freqMHz.toFixed(3),
      }

      // Emit cursor position for synced charts
      lastEmittedCursorFreq = freqHz
      emit('cursor-move', freqHz)
    })
    .on('mouseleave', () => {
      cursorLine.attr('opacity', 0)
      cursorInfo.value = null
      lastEmittedCursorFreq = null
      emit('cursor-move', null)
    })
    .on('click', (event) => {
      if (event.metaKey || event.ctrlKey) {
        // Ctrl+click: pin a frequency
        if (!effectiveXScale) return
        const [mx] = d3.pointer(event)
        const freqHz = effectiveXScale.invert(mx)
        const freqMHz = freqHz / 1e6
        emit('freq-pin', { freqHz, freqMHz })
        return
      }

      // Normal click: map click row to a scan in the buffer
      const buf = scanBuffer.value
      if (buf.length < 2) return

      const [, my] = d3.pointer(event)
      const oldestTs = buf[0].timestamp
      const newestTs = buf[buf.length - 1].timestamp
      const timeSpan = newestTs - oldestTs || 1
      const clickTime = oldestTs + (my / (plotHeight - 1 || 1)) * timeSpan

      // Find the closest scan to the click time
      let closest = buf[0]
      let closestDist = Math.abs(clickTime - closest.timestamp)
      for (let i = 1; i < buf.length; i++) {
        const dist = Math.abs(clickTime - buf[i].timestamp)
        if (dist < closestDist) {
          closest = buf[i]
          closestDist = dist
        }
      }

      emit('select', {
        timestamp: closest.timestamp,
        scan: {
          hz_lo: closest.hz_lo,
          hz_hi: closest.hz_hi,
          step: closest.step || (closest.hz_hi - closest.hz_lo) / closest.power.length,
          power: closest.power,
          timestamp: closest.timestamp,
        },
      })
    })

  // Long-press for touch devices (iPad — no ctrl/cmd key)
  let longPressTimer = null
  let longPressX = null

  mouseOverlay
    .on('touchstart.longpress', (event) => {
      if (event.touches.length !== 1) return
      const [mx] = d3.pointer(event.touches[0], mouseOverlay.node())
      longPressX = mx
      longPressTimer = setTimeout(() => {
        if (longPressX === null || !effectiveXScale) return
        const freqHz = effectiveXScale.invert(longPressX)
        const freqMHz = freqHz / 1e6
        emit('freq-pin', { freqHz, freqMHz })
        longPressX = null
      }, 500)
    })
    .on('touchmove.longpress', (event) => {
      if (longPressX === null) return
      const [mx] = d3.pointer(event.touches[0], mouseOverlay.node())
      if (Math.abs(mx - longPressX) > 10) {
        clearTimeout(longPressTimer)
        longPressX = null
      }
    })
    .on('touchend.longpress touchcancel.longpress', () => {
      clearTimeout(longPressTimer)
      longPressX = null
    })
}

// Append a live scan (flow up: push to end = bottom of canvas)
function addLiveScan(scan) {
  if (!scan?.power?.length) return

  const entry = {
    timestamp: Date.now(),
    power: scan.power,
    hz_lo: scan.hz_lo,
    hz_hi: scan.hz_hi,
  }

  scanBuffer.value.push(entry)
  const max = 2000 // ~30 min of live data at 1 scan/sec
  if (scanBuffer.value.length > max) {
    scanBuffer.value.splice(0, scanBuffer.value.length - max)
  }

  // Fast path: only paint the 1 new row instead of full repaint
  renderLiveRow(scan)
  updateTimeAxis()
  drawOverlays()
}

// Load scans into buffer (sorted chronologically, oldest first)
function loadHistorical(scans) {
  if (!scans || scans.length === 0) {
    scanBuffer.value = []
    if (ctx) ctx.clearRect(0, 0, canvasWidth, canvasHeight)
    return
  }

  // Sort oldest first (flow up: oldest at top)
  const sorted = [...scans].sort((a, b) => {
    const tsA = a.timestamp || (a.scan?.timestamp ? new Date(a.scan.timestamp).getTime() : 0)
    const tsB = b.timestamp || (b.scan?.timestamp ? new Date(b.scan.timestamp).getTime() : 0)
    return tsA - tsB
  })

  scanBuffer.value = sorted.map(s => {
    const scan = s.scan || s
    return {
      timestamp: s.timestamp || new Date(scan.timestamp).getTime(),
      power: scan.power,
      hz_lo: scan.hz_lo,
      hz_hi: scan.hz_hi,
    }
  })

  renderWaterfall()
  updateTimeAxis()
  drawOverlays()
}

function clear() {
  scanBuffer.value = []
  if (ctx) ctx.clearRect(0, 0, canvasWidth, canvasHeight)
}

defineExpose({ clear })

// Watch live scans
watch(() => props.scan, (newScan) => {
  if (props.isLive && newScan?.power?.length) {
    addLiveScan(newScan)
  }
})

// Watch historical scans — the array ref is replaced wholesale on load, so shallow watch suffices
watch(() => props.historicalScans, (scans) => {
  loadHistorical(scans)
})

// Watch mode switch — pre-fill from historical in both modes
watch(() => props.isLive, () => {
  loadHistorical(props.historicalScans)
})

// Watch zoom changes from line chart
watch(() => props.visibleRange, () => {
  const [renderStartHz, renderStopHz] = getEffectiveRange()
  effectiveXScale = d3.scaleLinear()
    .domain([renderStartHz, renderStopHz])
    .range([0, plotWidth])
  renderWaterfall()
  drawOverlays()
})

// External cursor from another chart (e.g. line chart)
watch(() => props.cursorFreq, (freqHz) => {
  if (!svgRef.value || !effectiveXScale) return
  const svg = d3.select(svgRef.value)
  const cursorLine = svg.select('.cursor-line')

  // Ignore if this is our own emitted value bouncing back
  if (freqHz !== null && freqHz === lastEmittedCursorFreq) return

  if (freqHz === null) {
    cursorLine.attr('opacity', 0)
    cursorInfo.value = null
    return
  }

  const mx = effectiveXScale(freqHz)
  if (mx >= 0 && mx <= plotWidth) {
    cursorLine.attr('x1', mx).attr('x2', mx).attr('opacity', 0.6)
    cursorInfo.value = {
      x: mx + margin.left,
      freqMHz: (freqHz / 1e6).toFixed(3),
    }
  } else {
    cursorLine.attr('opacity', 0)
    cursorInfo.value = null
  }
})

// Highlight row matching the currently displayed scan
watch(() => props.highlightTime, () => {
  drawOverlays()
})

// Pinned frequency markers
watch(() => props.pinnedFreqs, () => {
  drawOverlays()
})

// Draw highlight row and pinned frequency markers on the SVG overlay
function drawOverlays() {
  if (!svgRef.value || !effectiveXScale) return
  const svg = d3.select(svgRef.value)

  // Ensure overlay group exists
  let overlayGroup = svg.select('.chart-overlays')
  if (overlayGroup.empty()) {
    const chart = svg.select('g')
    if (chart.empty()) return
    overlayGroup = chart.append('g').attr('class', 'chart-overlays')
  }
  overlayGroup.selectAll('*').remove()

  // Highlight row
  if (props.highlightTime !== null) {
    const buf = scanBuffer.value
    if (buf.length >= 2) {
      const oldestTs = buf[0].timestamp
      const newestTs = buf[buf.length - 1].timestamp
      const timeSpan = newestTs - oldestTs || 1
      const rowY = ((props.highlightTime - oldestTs) / timeSpan) * (plotHeight - 1)
      if (rowY >= 0 && rowY <= plotHeight) {
        overlayGroup.append('line')
          .attr('x1', 0).attr('y1', rowY)
          .attr('x2', plotWidth).attr('y2', rowY)
          .attr('stroke', 'rgba(0, 255, 255, 0.6)')
          .attr('stroke-width', 2)
      }
    }
  }

  // Pinned frequency vertical markers
  for (const pin of props.pinnedFreqs) {
    const x = effectiveXScale(pin.freqHz)
    if (x >= 0 && x <= plotWidth) {
      overlayGroup.append('line')
        .attr('x1', x).attr('y1', 0)
        .attr('x2', x).attr('y2', plotHeight)
        .attr('stroke', pin.color)
        .attr('stroke-width', 1)
        .attr('stroke-dasharray', '4,2')
        .attr('opacity', 0.7)
    }
  }
}

// Resize handling
let resizeObserver = null

function handleResize() {
  buildAxes()
  renderWaterfall()
  renderLegend()
  drawOverlays()
}

onMounted(() => {
  nextTick(() => {
    buildAxes()
    renderLegend()
    // Pre-fill from historical data (works for both live and historical mode)
    loadHistorical(props.historicalScans)
  })

  if (container.value) {
    resizeObserver = new ResizeObserver(() => handleResize())
    resizeObserver.observe(container.value)
  }
})

onUnmounted(() => {
  if (resizeObserver) resizeObserver.disconnect()
})

// Color legend labels
const legendLabels = computed(() => {
  const labels = []
  const step = 30
  for (let db = maxDb; db >= minDb; db -= step) {
    labels.push(db)
  }
  return labels
})
</script>

<template>
  <div ref="container" class="spectrogram-chart w-full relative" :style="{ height: `${height}px` }">
    <!-- Canvas for heatmap (positioned in plot area) -->
    <canvas
      ref="canvasRef"
      class="absolute"
      style="image-rendering: pixelated;"
    />

    <!-- SVG overlay for time axis + cursor -->
    <svg
      ref="svgRef"
      class="absolute top-0 left-0 w-full"
      :style="{ height: `${height}px` }"
    />

    <!-- Color scale legend -->
    <div
      class="absolute flex flex-col items-center"
      :style="{
        right: '4px',
        top: `${margin.top}px`,
        height: `${height - margin.top - margin.bottom}px`,
        width: '16px',
      }"
    >
      <canvas
        ref="legendCanvas"
        class="w-full h-full rounded-sm"
        width="12"
        :height="height - margin.top - margin.bottom"
        style="image-rendering: pixelated;"
      />
    </div>
    <div
      class="absolute flex flex-col justify-between text-right"
      :style="{
        right: '22px',
        top: `${margin.top}px`,
        height: `${height - margin.top - margin.bottom}px`,
        width: '28px',
      }"
    >
      <span
        v-for="db in legendLabels"
        :key="db"
        class="text-gray-500 leading-none"
        style="font-size: 8px;"
      >{{ db }}</span>
    </div>

    <!-- Cursor tooltip -->
    <div
      v-if="cursorInfo"
      class="absolute pointer-events-none bg-gray-900/90 border border-cyan-500/50 rounded px-2 py-1 text-xs"
      :style="{
        left: `${cursorInfo.x + 10}px`,
        top: '4px',
      }"
    >
      <span class="text-cyan-400 font-mono">{{ cursorInfo.freqMHz }} MHz</span>
    </div>
  </div>
</template>

<style scoped>
.spectrogram-chart {
  position: relative;
  touch-action: manipulation;
}
</style>
