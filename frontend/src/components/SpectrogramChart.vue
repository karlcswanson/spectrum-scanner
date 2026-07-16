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

const emit = defineEmits(['cursor-move', 'select', 'freq-pin', 'zoom'])

const container = ref(null)
const canvasRef = ref(null)      // high-res layer (max-pool, chunked, fades in when ready)
const loCanvasRef = ref(null)    // low-res layer (nth-point, fast, always behind — tracks zoom)
const svgRef = ref(null)
const legendCanvas = ref(null)

// Interactive level-of-detail: the fast low-res layer shows during zoom/slide
// while the high-res layer re-renders hidden, then fades to the front when done.
const hiReady = ref(true)

// dBm range for color mapping (adjustable per-instance, persisted per band)
const DEFAULT_MIN_DB = -110
const DEFAULT_MAX_DB = -20

function storageKey() {
  return props.band?.name ? `wf-color:${props.band.name}` : null
}

function loadColorScale() {
  const key = storageKey()
  if (!key) return [DEFAULT_MIN_DB, DEFAULT_MAX_DB]
  try {
    const saved = JSON.parse(localStorage.getItem(key))
    if (saved && typeof saved.min === 'number' && typeof saved.max === 'number') {
      return [saved.min, saved.max]
    }
  } catch {}
  return [DEFAULT_MIN_DB, DEFAULT_MAX_DB]
}

const [initMin, initMax] = loadColorScale()
const colorMin = ref(initMin)
const colorMax = ref(initMax)
const dbRange = computed(() => colorMax.value - colorMin.value)
const legendExpanded = ref(false)

// Match D3SpectrumChart left/right margins for x-axis alignment. No own x-axis.
// Updated dynamically in buildAxes() for narrow screens.
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
  const clamped = Math.max(colorMin.value, Math.min(colorMax.value, dbm))
  return Math.round(((clamped - colorMin.value) / dbRange.value) * 255)
}

// Hot-loop variant: takes the color range as plain numbers so the per-pixel
// render loops don't hit a reactive `.value` getter hundreds of thousands of
// times per frame. Callers hoist `colorMin.value`/`colorMax.value` once.
function dbmToIndexFast(dbm, cMin, cMax, range) {
  const clamped = dbm < cMin ? cMin : (dbm > cMax ? cMax : dbm)
  return Math.round(((clamped - cMin) / range) * 255)
}

// Chart dimensions
let plotWidth = 0
let plotHeight = 0
let canvasWidth = 0
let canvasHeight = 0

// The low-res layer draws into a buffer this many times smaller in each axis
// (CSS stretches it back to full size — blocky, which is fine for a placeholder),
// so it costs ~LO_SCALE² less to render than the high-res layer.
const LO_SCALE = 2
let loCanvasWidth = 0
let loCanvasHeight = 0

// Full band frequency range (from band prop)
let startHz = 0
let stopHz = 0

let ctx = null
let loCtx = null
let effectiveXScale = null
let zoomBehavior = null
let xScaleBase = null
// Freq domain THIS waterfall last emitted via a continuous pan/wheel gesture. Lets us
// recognise the prop echo of our own gesture and NOT re-apply the zoom transform
// mid-drag (which would fight the active gesture).
let lastEmittedDomain = null
// True while we're the active pan/zoom driver (a d3.zoom gesture is in progress) and
// for a short settle window after it ends. During this time the visibleRange prop is
// just echoing our own gesture back — including the spectrum chart's setZoom transition
// replaying intermediate ranges — so we must ignore it or it snaps our transform back.
let panning = false
let panSettleTimer = null

const cursorInfo = ref(null)

// Effective frequency range currently shown. effectiveXScale is the live source of
// truth (updated by pan/wheel gestures and by external zoom sync); fall back to the
// prop / full band before it exists.
function getEffectiveRange() {
  if (effectiveXScale) return effectiveXScale.domain()
  return externalRange()
}

// The externally-driven range (from the spectrum chart, via the prop) or full band.
function externalRange() {
  if (props.visibleRange) return props.visibleRange
  return [startHz, stopHz]
}

// True when `range` matches our own most recent pan/wheel emit (it round-trips back to
// us through the prop; re-applying the transform mid-gesture would fight the drag).
function isEcho(range) {
  if (!lastEmittedDomain) return false
  const tol = Math.max(1, (stopHz - startHz) * 1e-4)
  return Math.abs(lastEmittedDomain[0] - range[0]) < tol &&
         Math.abs(lastEmittedDomain[1] - range[1]) < tol
}

// Align the d3.zoom transform to a freq domain without emitting (programmatic zoom
// events carry no sourceEvent, so the handler won't propagate). Mirrors the spectrum
// chart's setZoom so both charts share one pan/zoom model.
function syncZoomTransform(domain) {
  if (!zoomBehavior || !xScaleBase || !svgRef.value) return
  const [loHz, hiHz] = domain
  if (!(hiHz > loHz)) return
  const k = (stopHz - startHz) / (hiHz - loHz)
  const tx = -xScaleBase(loHz) * k
  const zoomEl = d3.select(svgRef.value).select('.brush .overlay')
  if (zoomEl.empty()) return
  zoomEl.call(zoomBehavior.transform, d3.zoomIdentity.translate(tx, 0).scale(k))
}

// Max dBm over the frequency bins that fall under one pixel column — the hottest
// bin, so a narrow strong signal between sampled bins survives instead of being
// dropped by single-sample striding. Returns null when the column is wholly
// outside the scan's frequency range (caller paints the floor color).
function columnMaxDbm(power, freqHz, hzPerPixel, scanHzLo, scanHzPerSample, scanLen) {
  let lo = Math.floor((freqHz - scanHzLo) / scanHzPerSample)
  let hi = Math.floor((freqHz + hzPerPixel - scanHzLo) / scanHzPerSample)
  if (hi < 0 || lo >= scanLen) return null
  if (lo < 0) lo = 0
  if (hi >= scanLen) hi = scanLen - 1
  let m = power[lo]
  for (let j = lo + 1; j <= hi; j++) {
    if (power[j] > m) m = power[j]
  }
  return m
}

// Full redraw of the waterfall from buffer (used for historical load, zoom,
// resize). A full-res redraw of a wide canvas can take a few hundred ms, so it
// is CHUNKED: rows are painted in ~8ms slices across animation frames, and the
// partially-filled image is blitted after each slice. This keeps the main thread
// responsive (no single long task) while staying full-res on the main thread. A
// newer render (`renderGen`) supersedes any in-flight one. Each render seeds its
// buffer from the CURRENT canvas (not a blank one), so on zoom the previous frame
// stays visible and is overwritten row-by-row instead of flashing blank.
let rafHandle = null
let renderGen = 0

function cancelChunkedRender() {
  renderGen++
  if (rafHandle) { cancelAnimationFrame(rafHandle); rafHandle = null }
}

function renderWaterfall() {
  if (!ctx || canvasWidth === 0 || canvasHeight === 0) return

  const buf = scanBuffer.value
  if (buf.length === 0) {
    cancelChunkedRender()
    ctx.clearRect(0, 0, canvasWidth, canvasHeight)
    return
  }

  const [renderStartHz, renderStopHz] = getEffectiveRange()
  if (renderStopHz <= renderStartHz) return
  const hzPerPixel = (renderStopHz - renderStartHz) / canvasWidth

  // Seed from the current canvas so un-rendered rows keep the previous frame
  // (no blank flash); rendered rows overwrite it. Context is willReadFrequently.
  const imgData = ctx.getImageData(0, 0, canvasWidth, canvasHeight)
  const pixels32 = new Uint32Array(imgData.data.buffer)

  const oldestTs = buf[0].timestamp
  const newestTs = buf[buf.length - 1].timestamp
  const timeSpan = newestTs - oldestTs || 1
  const cMin = colorMin.value, cMax = colorMax.value, range = (cMax - cMin) || 1

  cancelChunkedRender()
  const gen = renderGen
  let row = 0
  let searchIdx = 0

  const renderChunk = () => {
    if (gen !== renderGen) return // superseded by a newer render
    const t0 = performance.now()
    while (row < canvasHeight && performance.now() - t0 < 8) {
      const r = row++
      const rowTime = oldestTs + (r / (canvasHeight - 1 || 1)) * timeSpan
      while (searchIdx < buf.length - 1 && buf[searchIdx + 1].timestamp <= rowTime) {
        searchIdx++
      }
      if (rowTime - buf[searchIdx].timestamp > 120000) continue

      const scan = buf[searchIdx]
      const power = scan.power
      const scanHzLo = scan.hz_lo
      const scanLen = power.length
      const scanHzPerSample = (scan.hz_hi - scanHzLo) / scanLen
      const rowOffset = r * canvasWidth

      for (let col = 0; col < canvasWidth; col++) {
        const freqHz = renderStartHz + col * hzPerPixel
        const dbm = columnMaxDbm(power, freqHz, hzPerPixel, scanHzLo, scanHzPerSample, scanLen)
        pixels32[rowOffset + col] = VIRIDIS_U32[dbmToIndexFast(dbm === null ? cMin : dbm, cMin, cMax, range)]
      }
    }

    ctx.putImageData(imgData, 0, 0)
    if (row < canvasHeight) {
      rafHandle = requestAnimationFrame(renderChunk)
    } else {
      rafHandle = null
      hiReady.value = true // full-res render done → fade the hi layer to the front
    }
  }

  renderChunk() // first slice runs now; the rest are scheduled per frame
}

// Low-res layer: fast nth-point (single-sample-per-column) render. It skips the
// per-column max-pool, so it's ~15x cheaper — cheap enough to run synchronously
// on every zoom/slide, giving an instant preview that tracks the line chart while
// the high-res layer re-renders behind the scenes.
function renderLoRes() {
  if (!loCtx || loCanvasWidth === 0 || loCanvasHeight === 0) return
  const buf = scanBuffer.value
  if (buf.length === 0) {
    loCtx.clearRect(0, 0, loCanvasWidth, loCanvasHeight)
    return
  }

  const [renderStartHz, renderStopHz] = getEffectiveRange()
  if (renderStopHz <= renderStartHz) return
  const hzPerPixel = (renderStopHz - renderStartHz) / loCanvasWidth

  const imgData = loCtx.createImageData(loCanvasWidth, loCanvasHeight)
  const pixels32 = new Uint32Array(imgData.data.buffer)

  const oldestTs = buf[0].timestamp
  const newestTs = buf[buf.length - 1].timestamp
  const timeSpan = newestTs - oldestTs || 1
  const cMin = colorMin.value, cMax = colorMax.value, range = (cMax - cMin) || 1

  let searchIdx = 0
  for (let row = 0; row < loCanvasHeight; row++) {
    const rowTime = oldestTs + (row / (loCanvasHeight - 1 || 1)) * timeSpan
    while (searchIdx < buf.length - 1 && buf[searchIdx + 1].timestamp <= rowTime) {
      searchIdx++
    }
    if (rowTime - buf[searchIdx].timestamp > 120000) continue

    const scan = buf[searchIdx]
    const power = scan.power
    const scanHzLo = scan.hz_lo
    const scanLen = power.length
    const scanHzPerSample = (scan.hz_hi - scanHzLo) / scanLen
    const rowOffset = row * loCanvasWidth

    for (let col = 0; col < loCanvasWidth; col++) {
      const freqHz = renderStartHz + col * hzPerPixel
      const sampleIdx = (freqHz - scanHzLo) / scanHzPerSample
      const dbm = (sampleIdx < 0 || sampleIdx >= scanLen) ? cMin : power[Math.round(sampleIdx)]
      pixels32[rowOffset + col] = VIRIDIS_U32[dbmToIndexFast(dbm, cMin, cMax, range)]
    }
  }
  loCtx.putImageData(imgData, 0, 0)
}

// Show the low-res layer instantly, then (debounced) kick the high-res redraw
// which fades to the front on completion. Used for zoom/slide/color/resize.
let hiTimer = null
function refreshWaterfall(immediate = false) {
  hiReady.value = false // reveal the low-res layer
  renderLoRes()
  if (immediate) {
    if (hiTimer) { clearTimeout(hiTimer); hiTimer = null }
    renderWaterfall()
    return
  }
  if (hiTimer) clearTimeout(hiTimer)
  hiTimer = setTimeout(() => { hiTimer = null; renderWaterfall() }, 140)
}

// Fast path: shift canvas up by 1 row, paint only the newest scan at the bottom
function renderLiveRow(scan) {
  if (!ctx || canvasWidth === 0 || canvasHeight === 0) return
  if (!scan?.power?.length) return
  // A full chunked redraw is in flight and owns the canvas; skip the shift-and-
  // paint (which would corrupt the partially-drawn image). The new scan is in the
  // buffer, so it lands on the next full render / subsequent live rows.
  if (rafHandle) return

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
    const dbm = columnMaxDbm(power, freqHz, hzPerPixel, scanHzLo, scanHzPerSample, scanLen)
    rowPixels32[col] = VIRIDIS_U32[dbmToIndex(dbm === null ? colorMin.value : dbm)]
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

  // Responsive margins matching D3SpectrumChart
  const isNarrow = totalWidth < 500
  margin.left = isNarrow ? 35 : 55
  margin.right = isNarrow ? 15 : 50

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

  // High-res layer: full internal resolution (sharp). Low-res layer: a smaller
  // internal buffer (LO_SCALE× smaller per axis) stretched by CSS to the same
  // display size — blocky, but ~LO_SCALE² cheaper so it can render synchronously
  // on every zoom/slide as an instant placeholder.
  if (canvasRef.value) {
    const el = canvasRef.value
    el.width = canvasWidth
    el.height = canvasHeight
    el.style.width = canvasWidth + 'px'
    el.style.height = canvasHeight + 'px'
    el.style.left = margin.left + 'px'
    el.style.top = margin.top + 'px'
    ctx = el.getContext('2d', { willReadFrequently: true })
  }
  if (loCanvasRef.value) {
    const el = loCanvasRef.value
    loCanvasWidth = Math.max(1, Math.ceil(canvasWidth / LO_SCALE))
    loCanvasHeight = Math.max(1, Math.ceil(canvasHeight / LO_SCALE))
    el.width = loCanvasWidth
    el.height = loCanvasHeight
    el.style.width = canvasWidth + 'px' // display at full size; browser upscales the small buffer
    el.style.height = canvasHeight + 'px'
    el.style.left = margin.left + 'px'
    el.style.top = margin.top + 'px'
    loCtx = el.getContext('2d')
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

  // Overlays group for highlight row and pinned markers (below the brush overlay)
  chart.append('g').attr('class', 'chart-overlays')

  // Single interaction surface: the brush group. d3-brush creates its own
  // full-extent .overlay rect, and setupMouseHandlers hangs the cursor/click/
  // wheel listeners on that same rect — one overlay, two listener sets, so
  // there's no second transparent rect competing for pointer events.
  chart.append('g').attr('class', 'brush')

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

// Find the closest scan in the buffer to a target timestamp
function findClosestScan(targetTime) {
  const buf = scanBuffer.value
  if (buf.length < 2) return null
  let closest = buf[0]
  let closestDist = Math.abs(targetTime - closest.timestamp)
  for (let i = 1; i < buf.length; i++) {
    const dist = Math.abs(targetTime - buf[i].timestamp)
    if (dist < closestDist) { closest = buf[i]; closestDist = dist }
  }
  return closest
}

function emitScanSelect(scan) {
  emit('select', {
    timestamp: scan.timestamp,
    scan: {
      hz_lo: scan.hz_lo,
      hz_hi: scan.hz_hi,
      step: scan.step || (scan.hz_hi - scan.hz_lo) / scan.power.length,
      power: scan.power,
      timestamp: scan.timestamp,
    },
  })
}

function setupMouseHandlers() {
  const svg = d3.select(svgRef.value)
  const cursorLine = svg.select('.cursor-line')

  function clearCursor() {
    cursorLine.attr('opacity', 0)
    cursorInfo.value = null
    lastEmittedCursorFreq = null
    emit('cursor-move', null)
  }

  function showCursor(mx, freqHz, pin = false) {
    lastEmittedCursorFreq = freqHz
    emit('cursor-move', freqHz)

    if (pin) {
      cursorLine.attr('x1', mx).attr('x2', mx)
        .attr('opacity', 1).attr('stroke', '#00d4ff').attr('stroke-width', 2)
        .attr('stroke-dasharray', null)
    } else {
      cursorLine.attr('x1', mx).attr('x2', mx).attr('opacity', 0.6)
    }
    cursorInfo.value = {
      x: mx + margin.left,
      freqMHz: (freqHz / 1e6).toFixed(3),
      pinMode: pin,
    }
  }

  // Setup brush first so its overlay element exists for event attachment
  const brushGroup = svg.select('.brush')
  const brushBehavior = d3.brushX()
    .extent([[0, 0], [plotWidth, plotHeight]])
    .filter((event) => event.shiftKey) // only activate on Shift+drag
    .on('end', (event) => {
      if (!event.selection || !effectiveXScale) return
      const [x0, x1] = event.selection
      brushGroup.call(brushBehavior.move, null)
      if (x1 - x0 < 10) return
      const newLo = effectiveXScale.invert(x0)
      const newHi = effectiveXScale.invert(x1)
      emit('zoom', [newLo, newHi])
    })
  brushGroup.call(brushBehavior)
  brushGroup.select('.selection')
    .attr('fill', '#00d4ff')
    .attr('fill-opacity', 0.15)
    .attr('stroke', '#00d4ff')
    .attr('stroke-opacity', 0.5)

  // Pan/zoom mirroring the spectrum chart above: plain drag pans the frequency window,
  // wheel zooms about the cursor. Shift+drag is left to the brush (filtered out here);
  // dblclick reset is handled below. Attached to the brush's own overlay rect.
  xScaleBase = d3.scaleLinear().domain([startHz, stopHz]).range([0, plotWidth])
  zoomBehavior = d3.zoom()
    .scaleExtent([1, 20])
    .translateExtent([[0, 0], [plotWidth, plotHeight]])
    .extent([[0, 0], [plotWidth, plotHeight]])
    .filter((event) => {
      if (event.type === 'dblclick') return false
      if (event.type === 'mousedown' && event.shiftKey) return false // brush handles Shift+drag
      return true
    })
    .on('start', (event) => {
      // A real gesture (drag/wheel) makes us the driver: hold off on prop-driven syncs.
      if (event.sourceEvent) {
        if (panSettleTimer) { clearTimeout(panSettleTimer); panSettleTimer = null }
        panning = true
      }
    })
    .on('zoom', (event) => {
      effectiveXScale = event.transform.rescaleX(xScaleBase)
      if (!event.sourceEvent) return // programmatic sync — don't propagate or re-render
      const [lo, hi] = effectiveXScale.domain()
      const full = lo <= startHz + 1 && hi >= stopHz - 1
      lastEmittedDomain = full ? [startHz, stopHz] : [lo, hi]
      emit('zoom', full ? null : [lo, hi])
      refreshWaterfall()
      drawOverlays()
    })
    .on('end', (event) => {
      // Keep ignoring the prop for a beat: the spectrum chart's setZoom animates toward
      // our emitted domain over ~300ms, re-emitting intermediate ranges that would snap
      // our transform backwards right after the drag ends.
      if (event.sourceEvent) {
        if (panSettleTimer) clearTimeout(panSettleTimer)
        panSettleTimer = setTimeout(() => { panning = false; panSettleTimer = null }, 350)
      }
    })
  brushGroup.select('.overlay').call(zoomBehavior)
  // Start the transform at the current window so the first drag continues smoothly.
  syncZoomTransform(getEffectiveRange())

  // Cursor tracking and click handlers hang on the brush's own .overlay rect —
  // the single interaction surface. It already covers the full [0,0]→[plotWidth,
  // plotHeight] extent with pointer-events:all; we just add crosshair + our
  // listeners alongside d3-brush's own.
  const eventTarget = brushGroup.select('.overlay')
    .attr('pointer-events', 'all')
    .style('cursor', 'crosshair')

  eventTarget
    .on('mousemove', (event) => {
      if (!effectiveXScale) return
      const [mx] = d3.pointer(event)
      showCursor(mx, effectiveXScale.invert(mx))
    })
    .on('mouseleave', clearCursor)
    .on('click', (event) => {
      if (event.metaKey || event.ctrlKey) {
        if (!effectiveXScale) return
        const [mx] = d3.pointer(event)
        const freqHz = effectiveXScale.invert(mx)
        emit('freq-pin', { freqHz, freqMHz: freqHz / 1e6 })
        return
      }
      const [, my] = d3.pointer(event)
      const buf = scanBuffer.value
      if (buf.length < 2) return
      const timeSpan = buf[buf.length - 1].timestamp - buf[0].timestamp || 1
      const clickTime = buf[0].timestamp + (my / (plotHeight - 1 || 1)) * timeSpan
      const scan = findClosestScan(clickTime)
      if (scan) emitScanSelect(scan)
    })

  // Long-press + drag-to-refine for touch frequency pinning
  // Vertical drag = time scrub, hold still 400ms = freq pin
  let longPressTimer = null
  let longPressX = null
  let longPressActive = false
  let lastPinX = null
  let timeScrubbing = false
  let touchStartY = null

  function scrubToY(my) {
    const buf = scanBuffer.value
    if (buf.length < 2) return
    const timeSpan = buf[buf.length - 1].timestamp - buf[0].timestamp || 1
    const clampedY = Math.max(0, Math.min(plotHeight, my))
    const scrubTime = buf[0].timestamp + (clampedY / (plotHeight - 1 || 1)) * timeSpan
    const scan = findClosestScan(scrubTime)
    if (scan) emitScanSelect(scan)
  }

  eventTarget
    .on('touchstart.longpress', (event) => {
      if (event.touches.length !== 1) return
      const [mx, my] = d3.pointer(event.touches[0], eventTarget.node())
      longPressX = mx
      touchStartY = my
      longPressActive = false
      timeScrubbing = false
      lastPinX = null
      longPressTimer = setTimeout(() => {
        if (longPressX === null || !effectiveXScale) return
        longPressActive = true
        if (navigator.vibrate) navigator.vibrate(30)
        lastPinX = Math.max(0, Math.min(plotWidth, longPressX))
        showCursor(lastPinX, effectiveXScale.invert(lastPinX), true)
      }, 400)
    })
    .on('touchmove.longpress', (event) => {
      if (longPressX === null && !timeScrubbing) return
      const [mx, my] = d3.pointer(event.touches[0], eventTarget.node())

      if (longPressActive) {
        event.preventDefault()
        lastPinX = Math.max(0, Math.min(plotWidth, mx))
        showCursor(lastPinX, effectiveXScale.invert(lastPinX), true)
      } else if (timeScrubbing) {
        event.preventDefault()
        scrubToY(my)
      } else {
        const dy = Math.abs(my - touchStartY)
        if (dy > 10) {
          clearTimeout(longPressTimer)
          longPressX = null
          timeScrubbing = true
          event.preventDefault()
          scrubToY(my)
        } else if (Math.abs(mx - longPressX) > 10) {
          clearTimeout(longPressTimer)
          longPressX = null
        }
      }
    })
    .on('touchend.longpress touchcancel.longpress', () => {
      clearTimeout(longPressTimer)
      if (longPressActive && lastPinX !== null && effectiveXScale) {
        const freqHz = effectiveXScale.invert(lastPinX)
        emit('freq-pin', { freqHz, freqMHz: freqHz / 1e6 })
      }
      longPressActive = false
      longPressX = null
      touchStartY = null
      lastPinX = null
      timeScrubbing = false
      clearCursor()
    })

  // Double-click to reset zoom (d3.zoom's own dblclick is filtered out above so this
  // wins; emitting null round-trips back to a full-band window + identity transform).
  eventTarget.on('dblclick.zoom', () => {
    emit('zoom', null)
  })
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

  refreshWaterfall(true) // initial load: low-res instantly, high-res right after
  updateTimeAxis()
  drawOverlays()
}

function clear() {
  scanBuffer.value = []
  if (ctx) ctx.clearRect(0, 0, canvasWidth, canvasHeight)
}

defineExpose({ clear })

// Watch live scans — always paint new rows, regardless of scrubber mode.
// The waterfall is a continuous timeline that never stops scrolling.
watch(() => props.scan, (newScan) => {
  if (!newScan?.power?.length) return
  scanBuffer.value.push({
    timestamp: Date.now(),
    power: newScan.power,
    hz_lo: newScan.hz_lo,
    hz_hi: newScan.hz_hi,
  })
  const max = 2000
  if (scanBuffer.value.length > max) {
    scanBuffer.value.splice(0, scanBuffer.value.length - max)
  }
  renderLiveRow(newScan)
  updateTimeAxis()
  drawOverlays()
})

// Watch historical scans — full render on load or time range change
watch(() => props.historicalScans, (scans) => {
  loadHistorical(scans)
})

// Watch mode switch — only update overlays (highlight bar position).
// The waterfall itself keeps scrolling regardless of mode.
watch(() => props.isLive, () => {
  drawOverlays()
})

// Re-render when color scale range changes.
watch([colorMin, colorMax], () => {
  refreshWaterfall()
  renderLegend()
  const key = storageKey()
  if (key) {
    localStorage.setItem(key, JSON.stringify({ min: colorMin.value, max: colorMax.value }))
  }
})

// Watch zoom/slide from the line chart — the low-res layer re-renders instantly
// so the waterfall tracks the same range in tandem, while the high-res layer
// re-renders behind and fades to the front once it settles.
watch(() => props.visibleRange, () => {
  // We're mid-gesture (or just finished): our own transform is authoritative and the
  // prop is only echoing us back — ignore it so it can't snap the pan backwards.
  if (panning) return
  const [lo, hi] = externalRange()
  effectiveXScale = d3.scaleLinear()
    .domain([lo, hi])
    .range([0, plotWidth])
  // Echo of our own pan/wheel gesture: the transform is already correct and the
  // gesture already re-rendered — re-applying it would be redundant.
  if (isEcho([lo, hi])) return
  syncZoomTransform([lo, hi])
  refreshWaterfall()
  drawOverlays()
})

// External cursor from another chart — show native cursor
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
      .attr('stroke', '#666').attr('stroke-width', 1).attr('stroke-dasharray', '4,4')
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

  // Highlight row — the canvas is a scrolling tape via renderLiveRow.
  // Bottom row = newest scan, each row up = one scan earlier.
  // Count how many scans back the highlighted time is, map to pixel rows from bottom.
  if (props.highlightTime !== null) {
    const buf = scanBuffer.value
    if (buf.length >= 2) {
      // Find how many scans from the end the highlight time is
      // Binary search for the closest scan
      let closestIdx = buf.length - 1
      let closestDist = Math.abs(buf[closestIdx].timestamp - props.highlightTime)
      for (let i = buf.length - 2; i >= 0; i--) {
        const dist = Math.abs(buf[i].timestamp - props.highlightTime)
        if (dist < closestDist) {
          closestIdx = i
          closestDist = dist
        } else {
          break // buffer is sorted, distances will only increase from here
        }
      }
      // Rows from bottom: buf.length-1 = row plotHeight-1 (bottom), going up
      const scansFromEnd = buf.length - 1 - closestIdx
      const rowY = (plotHeight - 1) - scansFromEnd
      if (rowY >= 0 && rowY <= plotHeight) {
        overlayGroup.append('line')
          .attr('x1', 0).attr('y1', rowY)
          .attr('x2', plotWidth).attr('y2', rowY)
          .attr('stroke', 'rgba(0, 255, 255, 0.6)')
          .attr('stroke-width', 2)
      }
    }
  }

  // Pinned frequency vertical markers — selected pins are prominent, unselected are subtle
  for (const pin of props.pinnedFreqs) {
    const x = effectiveXScale(pin.freqHz)
    if (x >= 0 && x <= plotWidth) {
      if (pin.selected) {
        overlayGroup.append('line')
          .attr('x1', x).attr('y1', 0)
          .attr('x2', x).attr('y2', plotHeight)
          .attr('stroke', pin.color)
          .attr('stroke-width', 1)
          .attr('stroke-dasharray', '4,2')
          .attr('opacity', 0.7)
      } else {
        overlayGroup.append('line')
          .attr('x1', x).attr('y1', 0)
          .attr('x2', x).attr('y2', plotHeight)
          .attr('stroke', pin.color)
          .attr('stroke-width', 0.5)
          .attr('opacity', 0.15)
      }
    }
  }
}

// Resize handling
let resizeObserver = null

// ResizeObserver can fire spuriously (same size) — and re-rendering inside it
// can re-trigger it, forming a render loop. Only act on a real width change.
let lastResizeW = -1
function handleResize() {
  const w = container.value ? Math.round(container.value.getBoundingClientRect().width) : 0
  if (w === lastResizeW) return
  lastResizeW = w
  buildAxes()
  refreshWaterfall()
  renderLegend()
  drawOverlays()
}

function onDocumentClick(e) {
  if (legendExpanded.value && container.value && !e.target.closest('.legend-panel')) {
    legendExpanded.value = false
  }
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
  document.addEventListener('click', onDocumentClick)
})

onUnmounted(() => {
  if (resizeObserver) resizeObserver.disconnect()
  if (rafHandle) cancelAnimationFrame(rafHandle)
  if (hiTimer) clearTimeout(hiTimer)
  if (panSettleTimer) clearTimeout(panSettleTimer)
  document.removeEventListener('click', onDocumentClick)
})

// Color legend labels
const legendLabels = computed(() => {
  const labels = []
  const range = colorMax.value - colorMin.value
  const step = Math.max(10, Math.round(range / 3 / 10) * 10)
  for (let db = colorMax.value; db >= colorMin.value; db -= step) {
    labels.push(db)
  }
  return labels
})

function resetColorScale() {
  colorMin.value = DEFAULT_MIN_DB
  colorMax.value = DEFAULT_MAX_DB
  const key = storageKey()
  if (key) localStorage.removeItem(key)
}
</script>

<template>
  <div ref="container" class="spectrogram-chart w-full relative" :style="{ height: `${height}px` }">
    <!-- Low-res heatmap layer (behind): fast nth-point render, tracks zoom/slide -->
    <canvas
      ref="loCanvasRef"
      class="absolute wf-layer"
    />

    <!-- High-res heatmap layer (front): max-pool, chunked; fades in when ready -->
    <canvas
      ref="canvasRef"
      class="absolute wf-layer wf-hi"
      :style="{ opacity: hiReady ? 1 : 0 }"
    />

    <!-- SVG overlay for time axis + cursor -->
    <svg
      ref="svgRef"
      class="absolute top-0 left-0 w-full"
      :style="{ height: `${height}px` }"
    />

    <!-- Color scale legend (floats over waterfall plot area) -->
    <div
      class="absolute rounded-sm legend-panel"
      :class="legendExpanded ? 'legend-expanded' : ''"
      :style="{
        right: `${margin.right + 4}px`,
        top: `${margin.top + 4}px`,
        background: 'rgba(10, 10, 26, 0.85)',
        padding: legendExpanded ? '6px 8px' : '2px 3px',
      }"
      @click.stop
    >
      <!-- Collapsed: gradient + labels (tap to expand) -->
      <div
        class="flex items-center gap-0.5 cursor-pointer"
        :style="{ height: `${Math.min(height - margin.top - margin.bottom - 8, 80)}px` }"
        @click="legendExpanded = !legendExpanded"
      >
        <div class="flex flex-col justify-between text-right h-full" style="width: 20px;">
          <span
            v-for="db in legendLabels"
            :key="db"
            class="text-gray-400 leading-none"
            style="font-size: 7px;"
          >{{ db }}</span>
        </div>
        <canvas
          ref="legendCanvas"
          class="h-full rounded-sm"
          width="8"
          :height="Math.min(height - margin.top - margin.bottom - 8, 80)"
          style="image-rendering: pixelated; width: 8px;"
        />
      </div>

      <!-- Expanded: sliders + reset -->
      <div v-if="legendExpanded" class="legend-controls" @click.stop>
        <label class="legend-slider-row">
          <span class="legend-slider-label">Max</span>
          <input
            type="range"
            :min="colorMin + 10"
            max="-10"
            :value="colorMax"
            @input="colorMax = Number($event.target.value)"
            class="legend-slider"
          />
          <span class="legend-slider-value">{{ colorMax }}</span>
        </label>
        <label class="legend-slider-row">
          <span class="legend-slider-label">Min</span>
          <input
            type="range"
            min="-130"
            :max="colorMax - 10"
            :value="colorMin"
            @input="colorMin = Number($event.target.value)"
            class="legend-slider"
          />
          <span class="legend-slider-value">{{ colorMin }}</span>
        </label>
        <button class="legend-reset" @click="resetColorScale">Reset</button>
      </div>
    </div>

    <!-- Cursor tooltip -->
    <div
      v-if="cursorInfo"
      class="absolute pointer-events-none rounded px-2 py-1 text-xs"
      :class="cursorInfo.pinMode
        ? 'bg-cyan-900/95 border border-cyan-400/70'
        : 'bg-gray-900/90 border border-cyan-500/50'"
      :style="{
        left: `${cursorInfo.x + 10}px`,
        top: '4px',
      }"
    >
      <div v-if="cursorInfo.pinMode" class="text-cyan-300 font-semibold mb-0.5">Pin frequency</div>
      <span class="text-cyan-400 font-mono">{{ cursorInfo.freqMHz }} MHz</span>
    </div>
  </div>
</template>

<style scoped>
.spectrogram-chart {
  position: relative;
  touch-action: manipulation;
  -webkit-touch-callout: none;
  -webkit-user-select: none;
  user-select: none;
}

.wf-layer {
  image-rendering: pixelated;
  /* Display-only layers — all interaction (click/drag/cursor) goes to the SVG
     overlay on top; the canvases must not intercept pointer events. */
  pointer-events: none;
}

/* High-res layer fades in over the low-res layer once its render completes. */
.wf-hi {
  transition: opacity 0.18s ease;
}

.legend-panel {
  transition: padding 0.15s ease;
  z-index: 10;
}

.legend-controls {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-top: 6px;
  min-width: 120px;
}

.legend-slider-row {
  display: flex;
  align-items: center;
  gap: 4px;
}

.legend-slider-label {
  font-size: 8px;
  color: #9ca3af;
  width: 20px;
  text-align: right;
}

.legend-slider {
  flex: 1;
  height: 14px;
  accent-color: #06b6d4;
  cursor: pointer;
}

.legend-slider-value {
  font-size: 8px;
  color: #67e8f9;
  font-family: monospace;
  width: 24px;
  text-align: right;
}

.legend-reset {
  font-size: 8px;
  color: #9ca3af;
  background: rgba(255, 255, 255, 0.08);
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 3px;
  padding: 1px 6px;
  cursor: pointer;
  align-self: flex-end;
}

.legend-reset:hover {
  color: #e5e7eb;
  background: rgba(255, 255, 255, 0.15);
}
</style>
