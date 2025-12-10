<script setup>
import { ref, watch, onMounted, onUnmounted, computed } from 'vue'
import * as d3 from 'd3'

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
})

const container = ref(null)
const svgRef = ref(null)

// Track historical data for averaging and peak detection
const traceHistory = ref({}) // { traceId: { samples: [], peak: [], avg: [] } }
const maxHistorySamples = 30 // Number of samples to keep for averaging

// Color palette for multiple traces
const colorPalette = d3.schemeCategory10

// Normalized traces array - handles both single scan and multiple traces
const normalizedTraces = computed(() => {
  if (props.traces.length > 0) {
    return props.traces.map((trace, idx) => ({
      id: trace.id || `trace-${idx}`,
      name: trace.name || `Scanner ${idx + 1}`,
      scan: trace.scan,
      color: trace.color || colorPalette[idx % colorPalette.length],
    }))
  }
  if (props.scan?.power?.length > 0) {
    return [{
      id: 'default',
      name: 'Scanner',
      scan: props.scan,
      color: '#00d4ff',
    }]
  }
  return []
})

// ATSC TV channels for UHF band labeling
function getATSCChannels(startMHz, stopMHz) {
  const channels = []
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

// Update history for averaging/peak detection
function updateTraceHistory(traceId, power) {
  if (!traceHistory.value[traceId]) {
    traceHistory.value[traceId] = {
      samples: [],
      peak: [...power],
      avg: [...power],
    }
  }

  const history = traceHistory.value[traceId]

  // Add current sample
  history.samples.push([...power])

  // Keep only recent samples
  if (history.samples.length > maxHistorySamples) {
    history.samples.shift()
  }

  // Update peak (max hold)
  for (let i = 0; i < power.length; i++) {
    if (history.peak[i] === undefined || power[i] > history.peak[i]) {
      history.peak[i] = power[i]
    }
  }

  // Update average
  history.avg = new Array(power.length).fill(0)
  for (const sample of history.samples) {
    for (let i = 0; i < sample.length; i++) {
      history.avg[i] += sample[i] / history.samples.length
    }
  }
}

// Reset peak hold for a trace
function resetPeak(traceId) {
  if (traceHistory.value[traceId]) {
    traceHistory.value[traceId].peak = []
  }
}

// Main drawing function using D3
function draw() {
  if (!svgRef.value || !container.value) return

  const rect = container.value.getBoundingClientRect()
  const width = rect.width
  const height = props.height
  const margin = { top: 20, right: 50, bottom: 50, left: 55 }
  const plotWidth = width - margin.left - margin.right
  const plotHeight = height - margin.top - margin.bottom

  // dB scale for spectrum analyzers
  const minDb = -110
  const maxDb = -20

  // Determine frequency range from traces or band
  let startHz, stopHz
  const validTraces = normalizedTraces.value.filter(t => t.scan?.power?.length > 0)

  if (validTraces.length > 0) {
    // Use the widest range from all traces
    startHz = Math.min(...validTraces.map(t => t.scan.hz_lo))
    stopHz = Math.max(...validTraces.map(t => t.scan.hz_hi))
  } else if (props.band) {
    startHz = props.band.start_hz
    stopHz = props.band.stop_hz
  } else {
    startHz = 470e6
    stopHz = 608e6
  }

  const startMHz = startHz / 1e6
  const stopMHz = stopHz / 1e6
  const spanMHz = stopMHz - startMHz

  // Only use ATSC channel grid if we're in the actual TV band (470-608 MHz)
  const channels = getATSCChannels(startMHz, stopMHz)
  const isUHF = channels.length > 0

  // Select and clear SVG
  const svg = d3.select(svgRef.value)
  svg.selectAll('*').remove()

  // Set SVG dimensions
  svg
    .attr('width', width)
    .attr('height', height)
    .style('background', '#0a0a1a')

  // Create chart group with margins
  const chart = svg
    .append('g')
    .attr('transform', `translate(${margin.left},${margin.top})`)

  // Create scales
  const xScale = d3.scaleLinear()
    .domain([startHz, stopHz])
    .range([0, plotWidth])

  const yScale = d3.scaleLinear()
    .domain([minDb, maxDb])
    .range([plotHeight, 0])

  // Draw grid lines
  const gridGroup = chart.append('g').attr('class', 'grid')

  // Vertical grid lines
  if (isUHF) {
    // UHF: 6 MHz channel boundaries (channels already computed above)
    channels.forEach((ch, idx) => {
      if (ch.start >= startMHz) {
        const x = xScale(ch.start * 1e6)
        gridGroup.append('line')
          .attr('x1', x).attr('y1', 0)
          .attr('x2', x).attr('y2', plotHeight)
          .attr('stroke', '#1a1a3e')
          .attr('stroke-width', 1)
      }
      if (idx === channels.length - 1 && ch.end <= stopMHz) {
        const x = xScale(ch.end * 1e6)
        gridGroup.append('line')
          .attr('x1', x).attr('y1', 0)
          .attr('x2', x).attr('y2', plotHeight)
          .attr('stroke', '#1a1a3e')
          .attr('stroke-width', 1)
      }
    })
  } else {
    // Default frequency grid
    const freqStep = spanMHz > 100 ? 20 : spanMHz > 50 ? 10 : spanMHz > 20 ? 5 : spanMHz > 10 ? 2 : 1
    for (let f = Math.ceil(startMHz / freqStep) * freqStep; f <= stopMHz; f += freqStep) {
      const x = xScale(f * 1e6)
      gridGroup.append('line')
        .attr('x1', x).attr('y1', 0)
        .attr('x2', x).attr('y2', plotHeight)
        .attr('stroke', '#1a1a3e')
        .attr('stroke-width', 1)
    }
  }

  // Horizontal grid lines (dB)
  const dbStep = 20
  for (let db = minDb; db <= maxDb; db += dbStep) {
    const y = yScale(db)
    gridGroup.append('line')
      .attr('x1', 0).attr('y1', y)
      .attr('x2', plotWidth).attr('y2', y)
      .attr('stroke', '#1a1a3e')
      .attr('stroke-width', 1)
  }

  // X-axis
  const xAxisGroup = chart.append('g')
    .attr('transform', `translate(0,${plotHeight})`)

  if (isUHF) {
    // Show frequency at channel boundaries (channels already computed above)
    const tickValues = []
    channels.forEach((ch, idx) => {
      if (ch.start >= startMHz) tickValues.push(ch.start * 1e6)
      if (idx === channels.length - 1 && ch.end <= stopMHz) tickValues.push(ch.end * 1e6)
    })

    xAxisGroup.call(
      d3.axisBottom(xScale)
        .tickValues(tickValues)
        .tickFormat(d => (d / 1e6).toFixed(0))
    )
      .selectAll('text')
      .attr('fill', '#666')
      .style('font-size', '10px')

    xAxisGroup.selectAll('line').attr('stroke', '#666')
    xAxisGroup.select('.domain').attr('stroke', '#666')

    // Channel numbers below
    const channelGroup = chart.append('g')
      .attr('transform', `translate(0,${plotHeight + 28})`)

    channels.forEach(ch => {
      const x = xScale(ch.center * 1e6)
      if (x > 10 && x < plotWidth - 10) {
        channelGroup.append('text')
          .attr('x', x)
          .attr('y', 0)
          .attr('text-anchor', 'middle')
          .attr('fill', '#00d4ff')
          .style('font-size', '9px')
          .text(ch.num)
      }
    })
  } else {
    // Default axis
    xAxisGroup.call(
      d3.axisBottom(xScale)
        .ticks(10)
        .tickFormat(d => (d / 1e6).toFixed(1))
    )
      .selectAll('text')
      .attr('fill', '#666')
      .style('font-size', '10px')

    xAxisGroup.selectAll('line').attr('stroke', '#666')
    xAxisGroup.select('.domain').attr('stroke', '#666')
  }

  // Y-axis
  const yAxisGroup = chart.append('g')
  yAxisGroup.call(
    d3.axisLeft(yScale)
      .tickValues(d3.range(minDb, maxDb + 1, dbStep))
      .tickFormat(d => `${d}`)
  )
    .selectAll('text')
    .attr('fill', '#666')
    .style('font-size', '10px')

  yAxisGroup.selectAll('line').attr('stroke', '#666')
  yAxisGroup.select('.domain').attr('stroke', '#666')

  // Y-axis label
  chart.append('text')
    .attr('transform', 'rotate(-90)')
    .attr('x', -plotHeight / 2)
    .attr('y', -40)
    .attr('text-anchor', 'middle')
    .attr('fill', '#666')
    .style('font-size', '10px')
    .text('dBm')

  // X-axis label
  chart.append('text')
    .attr('x', plotWidth / 2)
    .attr('y', plotHeight + 42)
    .attr('text-anchor', 'middle')
    .attr('fill', '#666')
    .style('font-size', '10px')
    .text('MHz')

  // Create line generator
  const lineGenerator = d3.line()
    .x(d => d.x)
    .y(d => d.y)
    .curve(d3.curveLinear)

  // Draw traces
  const tracesGroup = chart.append('g').attr('class', 'traces')

  normalizedTraces.value.forEach((trace, traceIdx) => {
    if (!trace.scan?.power?.length) return

    const { hz_lo, hz_hi, step, power } = trace.scan

    // Update history for this trace
    updateTraceHistory(trace.id, power)
    const history = traceHistory.value[trace.id]

    // Convert power data to screen coordinates
    function powerToPoints(powerData) {
      const points = []
      const sampleStep = Math.max(1, Math.floor(powerData.length / plotWidth))

      for (let i = 0; i < powerData.length; i += sampleStep) {
        const freq = hz_lo + (i / powerData.length) * (hz_hi - hz_lo)
        const db = Math.max(minDb, Math.min(maxDb, powerData[i]))
        points.push({
          x: xScale(freq),
          y: yScale(db),
        })
      }
      return points
    }

    // Draw peak trace (behind current)
    if (props.showPeak && history.peak.length > 0) {
      const peakPoints = powerToPoints(history.peak)
      tracesGroup.append('path')
        .datum(peakPoints)
        .attr('d', lineGenerator)
        .attr('fill', 'none')
        .attr('stroke', d3.color(trace.color).darker(0.5).toString())
        .attr('stroke-width', 1)
        .attr('opacity', 0.5)
    }

    // Draw average trace
    if (props.showAverage && history.avg.length > 0) {
      const avgPoints = powerToPoints(history.avg)
      tracesGroup.append('path')
        .datum(avgPoints)
        .attr('d', lineGenerator)
        .attr('fill', 'none')
        .attr('stroke', d3.color(trace.color).brighter(0.3).toString())
        .attr('stroke-width', 1.5)
        .attr('stroke-dasharray', '4,2')
        .attr('opacity', 0.7)
    }

    // Draw current trace
    if (props.showCurrent) {
      const currentPoints = powerToPoints(power)
      tracesGroup.append('path')
        .datum(currentPoints)
        .attr('d', lineGenerator)
        .attr('fill', 'none')
        .attr('stroke', trace.color)
        .attr('stroke-width', 1)
    }
  })

  // Legend (only if multiple traces)
  if (normalizedTraces.value.length > 1) {
    const legendGroup = svg.append('g')
      .attr('transform', `translate(${width - margin.right - 10}, ${margin.top + 10})`)

    normalizedTraces.value.forEach((trace, idx) => {
      const legendItem = legendGroup.append('g')
        .attr('transform', `translate(0, ${idx * 18})`)

      legendItem.append('line')
        .attr('x1', -30)
        .attr('y1', 0)
        .attr('x2', -10)
        .attr('y2', 0)
        .attr('stroke', trace.color)
        .attr('stroke-width', 2)

      legendItem.append('text')
        .attr('x', -35)
        .attr('y', 4)
        .attr('text-anchor', 'end')
        .attr('fill', '#999')
        .style('font-size', '10px')
        .text(trace.name)
    })
  }
}

// Resize handling
let resizeObserver = null

function setupResizeObserver() {
  if (container.value) {
    resizeObserver = new ResizeObserver(() => {
      draw()
    })
    resizeObserver.observe(container.value)
  }
}

watch(() => [props.scan, props.traces, props.showCurrent, props.showAverage, props.showPeak], draw, { deep: true })

onMounted(() => {
  setupResizeObserver()
  draw()
})

onUnmounted(() => {
  if (resizeObserver) {
    resizeObserver.disconnect()
  }
})

// Expose reset function for parent components
defineExpose({
  resetPeak,
  resetAllPeaks: () => {
    Object.keys(traceHistory.value).forEach(id => resetPeak(id))
  }
})
</script>

<template>
  <div ref="container" class="d3-spectrum-chart w-full">
    <svg ref="svgRef" class="w-full rounded" :style="{ height: `${height}px` }"></svg>
  </div>
</template>

<style scoped>
.d3-spectrum-chart {
  position: relative;
}
</style>
