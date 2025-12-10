<script setup>
import { ref, watch, onMounted, onUnmounted } from 'vue'

const props = defineProps({
  scan: {
    type: Object,
    required: true,
  },
  band: {
    type: Object,
    default: null,
  },
  height: {
    type: Number,
    default: 300,
  },
})

const emit = defineEmits(['export'])

const canvas = ref(null)
let ctx = null

// ATSC TV channels: channel 14 starts at 470 MHz, each channel is 6 MHz wide
function getATSCChannels(startMHz, stopMHz) {
  const channels = []
  // Channel 14 starts at 470 MHz, channels 14-36 are 470-608 MHz
  for (let ch = 14; ch <= 36; ch++) {
    const chStartMHz = 470 + (ch - 14) * 6
    const chEndMHz = chStartMHz + 6
    const chCenterMHz = chStartMHz + 3
    if (chEndMHz > startMHz && chStartMHz < stopMHz) {
      channels.push({ num: ch, start: chStartMHz, end: chEndMHz, center: chCenterMHz })
    }
  }
  return channels
}

function draw() {
  if (!ctx || !canvas.value) return

  const rect = canvas.value.getBoundingClientRect()
  const width = rect.width
  const height = props.height
  const padding = { top: 20, right: 50, bottom: 45, left: 50 }
  const plotWidth = width - padding.left - padding.right
  const plotHeight = height - padding.top - padding.bottom

  // Clear canvas
  ctx.fillStyle = '#0a0a1a'
  ctx.fillRect(0, 0, width, height)

  // dB scale for spectrum analyzers
  const minDb = -110
  const maxDb = -20

  // Use scan data if available, otherwise use band info
  const hasScanData = props.scan?.power?.length > 0
  const startMHz = hasScanData ? props.scan.hz_lo / 1e6 : (props.band?.start_hz / 1e6 || 470)
  const stopMHz = hasScanData ? props.scan.hz_hi / 1e6 : (props.band?.stop_hz / 1e6 || 608)
  const spanMHz = stopMHz - startMHz

  // Detect if UHF band (for ATSC channel labeling)
  const isUHF = startMHz >= 450 && stopMHz <= 700

  if (isUHF) {
    // UHF: Draw vertical lines at 6 MHz channel boundaries
    const channels = getATSCChannels(startMHz, stopMHz)

    ctx.strokeStyle = '#1a1a3e'
    ctx.fillStyle = '#666'
    ctx.font = '10px sans-serif'
    ctx.textAlign = 'center'

    // Draw channel boundary lines and frequency labels
    channels.forEach((ch, idx) => {
      // Draw start boundary line
      if (ch.start >= startMHz) {
        const xStart = padding.left + ((ch.start - startMHz) / spanMHz) * plotWidth
        ctx.beginPath()
        ctx.moveTo(xStart, padding.top)
        ctx.lineTo(xStart, height - padding.bottom)
        ctx.stroke()
        ctx.fillText(`${ch.start}`, xStart, height - padding.bottom + 12)
      }

      // Draw end boundary for last channel
      if (idx === channels.length - 1 && ch.end <= stopMHz) {
        const xEnd = padding.left + ((ch.end - startMHz) / spanMHz) * plotWidth
        ctx.beginPath()
        ctx.moveTo(xEnd, padding.top)
        ctx.lineTo(xEnd, height - padding.bottom)
        ctx.stroke()
        ctx.fillText(`${ch.end}`, xEnd, height - padding.bottom + 12)
      }
    })

    // Draw channel numbers between boundaries
    ctx.fillStyle = '#00d4ff'
    ctx.font = '9px sans-serif'
    channels.forEach(ch => {
      const xCenter = padding.left + ((ch.center - startMHz) / spanMHz) * plotWidth
      if (xCenter > padding.left + 10 && xCenter < width - padding.right - 10) {
        ctx.fillText(`${ch.num}`, xCenter, height - padding.bottom + 24)
      }
    })
  } else {
    // Default frequency grid for other bands
    ctx.strokeStyle = '#1a1a3e'
    ctx.fillStyle = '#666'
    ctx.font = '10px sans-serif'
    ctx.textAlign = 'center'

    const freqStep = spanMHz > 100 ? 20 : spanMHz > 50 ? 10 : spanMHz > 20 ? 5 : spanMHz > 10 ? 2 : 1
    for (let f = Math.ceil(startMHz / freqStep) * freqStep; f <= stopMHz; f += freqStep) {
      const x = padding.left + ((f - startMHz) / spanMHz) * plotWidth
      ctx.beginPath()
      ctx.moveTo(x, padding.top)
      ctx.lineTo(x, height - padding.bottom)
      ctx.stroke()
      ctx.fillText(`${f}`, x, height - padding.bottom + 12)
    }
  }

  // Draw horizontal grid lines (dB)
  ctx.strokeStyle = '#1a1a3e'
  ctx.lineWidth = 1
  const dbStep = 20
  ctx.fillStyle = '#666'
  ctx.font = '10px sans-serif'
  ctx.textAlign = 'right'
  for (let db = minDb; db <= maxDb; db += dbStep) {
    const y = padding.top + plotHeight - ((db - minDb) / (maxDb - minDb)) * plotHeight
    ctx.beginPath()
    ctx.moveTo(padding.left, y)
    ctx.lineTo(width - padding.right, y)
    ctx.stroke()
    ctx.fillText(`${db}`, padding.left - 5, y + 3)
  }

  // Draw spectrum line if we have data
  if (hasScanData) {
    ctx.strokeStyle = '#00d4ff'
    ctx.lineWidth = 1
    ctx.beginPath()

    const step = Math.max(1, Math.floor(props.scan.power.length / plotWidth))

    for (let i = 0; i < props.scan.power.length; i += step) {
      const x = padding.left + (i / props.scan.power.length) * plotWidth
      const db = Math.max(minDb, Math.min(maxDb, props.scan.power[i]))
      const y = padding.top + plotHeight - ((db - minDb) / (maxDb - minDb)) * plotHeight

      if (i === 0) {
        ctx.moveTo(x, y)
      } else {
        ctx.lineTo(x, y)
      }
    }
    ctx.stroke()
  }
}

function setupCanvas() {
  if (!canvas.value) return

  const rect = canvas.value.getBoundingClientRect()
  canvas.value.width = rect.width * window.devicePixelRatio
  canvas.value.height = props.height * window.devicePixelRatio

  ctx = canvas.value.getContext('2d')
  ctx.scale(window.devicePixelRatio, window.devicePixelRatio)

  draw()
}

function exportCSV() {
  emit('export')
}

watch(() => props.scan, draw, { deep: true })

onMounted(() => {
  setupCanvas()
  window.addEventListener('resize', setupCanvas)
})

onUnmounted(() => {
  window.removeEventListener('resize', setupCanvas)
})
</script>

<template>
  <div class="spectrum-chart">
    <canvas
      ref="canvas"
      class="w-full rounded"
      :style="{ height: `${height}px`, background: '#0a0a1a' }"
    ></canvas>
  </div>
</template>

<style scoped>
.spectrum-chart {
  position: relative;
}
</style>
