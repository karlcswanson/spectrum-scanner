<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import * as d3 from 'd3'

const props = defineProps({
  scannerId: {
    type: String,
    required: true,
  },
  bandName: {
    type: String,
    default: null,
  },
  // Array of timestamps where scans exist
  // Format: [{ id, timestamp, band__name }]
  timeline: {
    type: Array,
    default: () => [],
  },
  // Maximum hours to show (default 24)
  maxHours: {
    type: Number,
    default: 24,
  },
  height: {
    type: Number,
    default: 60,
  },
})

const emit = defineEmits(['select', 'live'])

const container = ref(null)
const svgRef = ref(null)
const selectedTime = ref(null)
const isLive = ref(true)
const isDragging = ref(false)

// Store xScale for drag operations
let currentXScale = null
let currentMarkers = []

// Filter timeline by band if specified
const filteredTimeline = computed(() => {
  if (!props.bandName) return props.timeline
  return props.timeline.filter(t => t.band__name === props.bandName)
})

// Time range
const timeRange = computed(() => {
  const now = new Date()
  const start = new Date(now.getTime() - props.maxHours * 60 * 60 * 1000)
  return { start, end: now }
})

function selectTime(time) {
  if (time === null) {
    // Go live
    isLive.value = true
    selectedTime.value = null
    emit('live')
  } else {
    isLive.value = false
    selectedTime.value = time
    emit('select', time)
  }
}

function goLive() {
  selectTime(null)
}

// Find closest scan to a given time
function findClosestScan(time) {
  if (currentMarkers.length === 0) return null

  let closest = null
  let closestDiff = Infinity
  for (const marker of currentMarkers) {
    const diff = Math.abs(marker.date - time)
    if (diff < closestDiff) {
      closestDiff = diff
      closest = marker
    }
  }
  return closest
}

function draw() {
  if (!svgRef.value || !container.value) return

  const rect = container.value.getBoundingClientRect()
  const width = rect.width
  const height = props.height
  const margin = { top: 5, right: 50, bottom: 25, left: 15 }
  const plotWidth = width - margin.left - margin.right
  const plotHeight = height - margin.top - margin.bottom

  const svg = d3.select(svgRef.value)
  svg.selectAll('*').remove()

  svg
    .attr('width', width)
    .attr('height', height)
    .style('background', '#1a1a2e')

  const chart = svg
    .append('g')
    .attr('transform', `translate(${margin.left},${margin.top})`)

  // Time scale
  const xScale = d3.scaleTime()
    .domain([timeRange.value.start, timeRange.value.end])
    .range([0, plotWidth])

  // Store for drag operations
  currentXScale = xScale

  // Draw time axis
  const tickCount = Math.min(12, Math.floor(plotWidth / 80))
  const xAxis = d3.axisBottom(xScale)
    .ticks(tickCount)
    .tickFormat(d => d3.timeFormat('%H:%M')(d))

  chart.append('g')
    .attr('transform', `translate(0,${plotHeight})`)
    .call(xAxis)
    .selectAll('text')
    .attr('fill', '#666')
    .style('font-size', '10px')

  chart.selectAll('.domain, .tick line')
    .attr('stroke', '#333')

  // Draw scan markers
  const markers = filteredTimeline.value
    .map(t => ({
      ...t,
      date: new Date(t.timestamp),
    }))
    .filter(t => t.date >= timeRange.value.start && t.date <= timeRange.value.end)

  // Store for drag operations
  currentMarkers = markers

  // Draw markers
  const markerRadius = 3
  chart.selectAll('.scan-marker')
    .data(markers)
    .join('circle')
    .attr('class', 'scan-marker')
    .attr('cx', d => xScale(d.date))
    .attr('cy', plotHeight / 2)
    .attr('r', markerRadius)
    .attr('fill', d => {
      if (selectedTime.value && Math.abs(d.date - selectedTime.value) < 1000) {
        return '#00d4ff'
      }
      return '#4a5568'
    })

  // Draw "now" indicator
  const nowX = xScale(new Date())
  chart.append('line')
    .attr('class', 'now-line')
    .attr('x1', nowX)
    .attr('y1', 0)
    .attr('x2', nowX)
    .attr('y2', plotHeight)
    .attr('stroke', isLive.value ? '#22c55e' : '#666')
    .attr('stroke-width', 1)
    .attr('stroke-dasharray', '4,2')

  // Create scrubber handle group
  const scrubberX = selectedTime.value ? xScale(selectedTime.value) : nowX
  const scrubber = chart.append('g')
    .attr('class', 'scrubber')
    .attr('transform', `translate(${Math.max(0, Math.min(plotWidth, scrubberX))}, 0)`)
    .style('cursor', 'ew-resize')

  // Scrubber line
  scrubber.append('line')
    .attr('x1', 0)
    .attr('y1', 0)
    .attr('x2', 0)
    .attr('y2', plotHeight)
    .attr('stroke', isLive.value ? '#22c55e' : '#00d4ff')
    .attr('stroke-width', 2)

  // Scrubber handle (triangle/arrow at top)
  scrubber.append('path')
    .attr('d', 'M-6,0 L6,0 L0,8 Z')
    .attr('fill', isLive.value ? '#22c55e' : '#00d4ff')

  // Scrubber handle (triangle at bottom)
  scrubber.append('path')
    .attr('d', `M-6,${plotHeight} L6,${plotHeight} L0,${plotHeight - 8} Z`)
    .attr('fill', isLive.value ? '#22c55e' : '#00d4ff')

  // Invisible wider rect for easier dragging
  scrubber.append('rect')
    .attr('x', -10)
    .attr('y', 0)
    .attr('width', 20)
    .attr('height', plotHeight)
    .attr('fill', 'transparent')

  // Track last emitted scan to avoid duplicate fetches
  let lastEmittedScanId = null

  // Drag behavior
  const drag = d3.drag()
    .on('start', () => {
      isDragging.value = true
      lastEmittedScanId = null
    })
    .on('drag', (event) => {
      const x = Math.max(0, Math.min(plotWidth, event.x))
      scrubber.attr('transform', `translate(${x}, 0)`)

      // Update line color while dragging
      scrubber.select('line').attr('stroke', '#00d4ff')
      scrubber.selectAll('path').attr('fill', '#00d4ff')

      // Find and show closest scan as we drag
      const time = xScale.invert(x)
      const closest = findClosestScan(time)
      if (closest && closest.id !== lastEmittedScanId) {
        lastEmittedScanId = closest.id
        selectTime(closest.date)
      }
    })
    .on('end', () => {
      isDragging.value = false
      // Snap to the currently selected scan position
      if (selectedTime.value) {
        const snapX = xScale(selectedTime.value)
        scrubber.attr('transform', `translate(${Math.max(0, Math.min(plotWidth, snapX))}, 0)`)
      }
      // Trigger redraw to update marker highlights
      draw()
    })

  scrubber.call(drag)

  // Click anywhere on timeline to seek (behind scrubber)
  chart.insert('rect', ':first-child')
    .attr('width', plotWidth)
    .attr('height', plotHeight)
    .attr('fill', 'transparent')
    .attr('cursor', 'pointer')
    .on('click', (event) => {
      const [x] = d3.pointer(event)
      const time = xScale.invert(x)
      const closest = findClosestScan(time)
      if (closest) {
        selectTime(closest.date)
      }
    })
}

// Resize handling
let resizeObserver = null

onMounted(() => {
  if (container.value) {
    resizeObserver = new ResizeObserver(() => draw())
    resizeObserver.observe(container.value)
  }
  draw()
})

// Don't redraw while dragging - it disrupts the drag interaction
watch(() => [props.timeline, selectedTime.value, isLive.value], () => {
  if (!isDragging.value) {
    draw()
  }
}, { deep: true })

// Format selected time for display
const selectedTimeDisplay = computed(() => {
  if (!selectedTime.value) return null
  return selectedTime.value.toLocaleString()
})
</script>

<template>
  <div class="time-scrubber bg-gray-900 rounded p-2">
    <div class="flex items-center justify-between mb-2">
      <div class="text-xs text-gray-500">
        <span v-if="isLive" class="text-green-400 font-semibold">LIVE</span>
        <span v-else>{{ selectedTimeDisplay }}</span>
      </div>
      <div class="flex items-center gap-2">
        <span class="text-xs text-gray-600">{{ filteredTimeline.length }} scans</span>
        <button
          @click="goLive"
          class="px-3 py-1 rounded text-xs font-semibold transition-colors"
          :class="isLive
            ? 'bg-green-600 text-white'
            : 'bg-gray-700 hover:bg-gray-600 text-gray-300'"
        >
          Live
        </button>
      </div>
    </div>
    <div ref="container" class="w-full">
      <svg ref="svgRef" class="w-full" :style="{ height: `${height}px` }"></svg>
    </div>
  </div>
</template>

<style scoped>
.time-scrubber {
  user-select: none;
}
</style>
