<script setup>
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import * as d3 from 'd3'
import { useScannersStore } from '../stores/scanners'

const store = useScannersStore()

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
  // External control: are we actually showing live data?
  showingLive: {
    type: Boolean,
    default: true,
  },
  // Currently selected/displayed time (for positioning scrubber)
  currentTime: {
    type: Date,
    default: null,
  },
  // Timestamp of last live scan received (triggers redraw to update "now" line)
  lastScanTime: {
    type: [Date, Number, String],
    default: null,
  },
  // Hide individual scan markers for better performance
  hideMarkers: {
    type: Boolean,
    default: false,
  },
})

const emit = defineEmits(['select', 'preview', 'live'])

const container = ref(null)
const svgRef = ref(null)
const isDragging = ref(false)

// Local state for drag operations - tracks where scrubber should be
const dragTime = ref(null)

// Effective selected time: use drag time during interaction, otherwise use prop
const selectedTime = computed(() => {
  if (dragTime.value) return dragTime.value
  return props.currentTime
})

// Is the display in live mode?
const isLive = computed(() => props.showingLive && !dragTime.value)

// Store xScale for drag operations
let currentXScale = null
let currentMarkers = []

// Filter timeline by band if specified
const filteredTimeline = computed(() => {
  if (!props.bandName) return props.timeline
  return props.timeline.filter(t => t.band__name === props.bandName)
})

// Time range - computed fresh in draw(), not cached
function getTimeRange() {
  const now = new Date()
  const start = new Date(now.getTime() - props.maxHours * 60 * 60 * 1000)
  return { start, end: now }
}

function goLive() {
  dragTime.value = null
  emit('live')
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


// RAF-based draw scheduling (no artificial delays, just sync to display refresh)
let pendingRAF = null

function scheduleDraw() {
  if (!pendingRAF) {
    pendingRAF = requestAnimationFrame(() => {
      pendingRAF = null
      draw()
    })
  }
}

// Cache parsed dates to avoid re-parsing on every draw
const parsedDates = new Map()
function getDate(timestamp) {
  if (!parsedDates.has(timestamp)) {
    parsedDates.set(timestamp, new Date(timestamp))
  }
  return parsedDates.get(timestamp)
}

// Track if SVG structure is initialized
let svgInitialized = false
let lastWidth = 0

function draw() {
  if (!svgRef.value || !container.value) return

  const rect = container.value.getBoundingClientRect()
  const width = rect.width
  const height = props.height
  const margin = { top: 5, right: 50, bottom: 25, left: 15 }
  const plotWidth = width - margin.left - margin.right
  const plotHeight = height - margin.top - margin.bottom

  const svg = d3.select(svgRef.value)

  // Only rebuild structure if width changed or not initialized
  if (!svgInitialized || width !== lastWidth) {
    svg.selectAll('*').remove()
    svg
      .attr('width', width)
      .attr('height', height)
      .style('background', '#1a1a2e')

    svg.append('g')
      .attr('class', 'chart')
      .attr('transform', `translate(${margin.left},${margin.top})`)

    svg.select('.chart').append('g').attr('class', 'axis')
      .attr('transform', `translate(0,${plotHeight})`)

    svg.select('.chart').append('g').attr('class', 'markers')
    svg.select('.chart').append('line').attr('class', 'now-line')
    svg.select('.chart').append('g').attr('class', 'scrubber')
    svg.select('.chart').insert('rect', ':first-child').attr('class', 'click-area')
      .attr('width', plotWidth)
      .attr('height', plotHeight)
      .attr('fill', 'transparent')
      .attr('cursor', 'pointer')

    svgInitialized = true
    lastWidth = width
  }

  const chart = svg.select('.chart')

  // Get fresh time range (not cached)
  const timeRange = getTimeRange()

  // Time scale
  const xScale = d3.scaleTime()
    .domain([timeRange.start, timeRange.end])
    .range([0, plotWidth])

  // Store for drag operations
  currentXScale = xScale

  // Update time axis
  const tickCount = Math.min(12, Math.floor(plotWidth / 80))
  const xAxis = d3.axisBottom(xScale)
    .ticks(tickCount)
    .tickFormat(d => d3.timeFormat('%H:%M')(d))

  chart.select('.axis')
    .call(xAxis)
    .selectAll('text')
    .attr('fill', '#666')
    .style('font-size', '10px')

  chart.selectAll('.domain, .tick line')
    .attr('stroke', '#333')

  // Get markers with cached dates (needed for drag operations even if not drawn)
  const allMarkers = filteredTimeline.value
    .map(t => ({
      ...t,
      date: getDate(t.timestamp),
    }))
    .filter(t => t.date >= timeRange.start && t.date <= timeRange.end)

  // Store all markers for drag operations (finding closest scan)
  currentMarkers = allMarkers

  // Only draw markers if not hidden
  if (!props.hideMarkers) {
    // Bin markers if there are too many (more than 1 per 2 pixels)
    const maxMarkers = Math.floor(plotWidth / 2)
    let markers = allMarkers
    if (allMarkers.length > maxMarkers) {
      // Bin by pixel position - keep one marker per bin
      const binned = new Map()
      for (const m of allMarkers) {
        const px = Math.floor(xScale(m.date))
        if (!binned.has(px)) {
          binned.set(px, m)
        }
      }
      markers = Array.from(binned.values())
    }

    // Update markers efficiently
    const markerRadius = 3
    chart.select('.markers').selectAll('.scan-marker')
      .data(markers, d => d.id)
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
  } else {
    // Clear any existing markers
    chart.select('.markers').selectAll('.scan-marker').remove()
  }

  // Update "now" indicator
  const nowX = xScale(new Date())
  chart.select('.now-line')
    .attr('x1', nowX)
    .attr('y1', 0)
    .attr('x2', nowX)
    .attr('y2', plotHeight)
    .attr('stroke', isLive.value ? '#22c55e' : '#666')
    .attr('stroke-width', 1)
    .attr('stroke-dasharray', '4,2')

  // Update scrubber position and colors
  const scrubberX = selectedTime.value ? xScale(selectedTime.value) : nowX
  const scrubber = chart.select('.scrubber')
    .attr('transform', `translate(${Math.max(0, Math.min(plotWidth, scrubberX))}, 0)`)
    .style('cursor', 'ew-resize')

  const scrubberColor = isLive.value ? '#22c55e' : '#00d4ff'

  // Only create scrubber elements once
  if (scrubber.select('line').empty()) {
    scrubber.append('line')
    scrubber.append('path').attr('class', 'top-handle')
    scrubber.append('path').attr('class', 'bottom-handle')
    scrubber.append('rect').attr('class', 'drag-area')
  }

  scrubber.select('line')
    .attr('x1', 0)
    .attr('y1', 0)
    .attr('x2', 0)
    .attr('y2', plotHeight)
    .attr('stroke', scrubberColor)
    .attr('stroke-width', 2)

  scrubber.select('.top-handle')
    .attr('d', 'M-6,0 L6,0 L0,8 Z')
    .attr('fill', scrubberColor)

  scrubber.select('.bottom-handle')
    .attr('d', `M-6,${plotHeight} L6,${plotHeight} L0,${plotHeight - 8} Z`)
    .attr('fill', scrubberColor)

  scrubber.select('.drag-area')
    .attr('x', -10)
    .attr('y', 0)
    .attr('width', 20)
    .attr('height', plotHeight)
    .attr('fill', 'transparent')

  // Only set up drag behavior once
  if (!scrubber.node().__dragInitialized) {
    scrubber.node().__dragInitialized = true
    let lastPreviewScanId = null

    const drag = d3.drag()
      .on('start', () => {
        isDragging.value = true
        lastPreviewScanId = null
      })
      .on('drag', (event) => {
        // Immediately follow the mouse for responsive feel
        const x = Math.max(0, Math.min(plotWidth, event.x))
        scrubber.attr('transform', `translate(${x}, 0)`)

        // Update line color while dragging
        scrubber.select('line').attr('stroke', '#00d4ff')
        scrubber.selectAll('path').attr('fill', '#00d4ff')

        // Find closest scan and emit preview (decimated) immediately
        const time = currentXScale.invert(x)
        const closest = findClosestScan(time)
        if (closest && closest.id !== lastPreviewScanId) {
          lastPreviewScanId = closest.id
          dragTime.value = closest.date
          emit('preview', closest.date)
        }
      })
      .on('end', (event) => {
        isDragging.value = false
        // On release, emit select for full resolution fetch
        const x = Math.max(0, Math.min(plotWidth, event.x))
        const time = currentXScale.invert(x)
        const closest = findClosestScan(time)
        if (closest) {
          dragTime.value = closest.date
          emit('select', closest.date)
        }
        // Redraw will snap scrubber to actual data point
        draw()
      })

    scrubber.call(drag)

    // Click anywhere on timeline to seek (full resolution immediately)
    chart.select('.click-area')
      .on('click', (event) => {
        const [x] = d3.pointer(event)
        const time = currentXScale.invert(x)
        const closest = findClosestScan(time)
        if (closest) {
          dragTime.value = closest.date
          emit('select', closest.date)
        }
      })
  }
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

onUnmounted(() => {
  if (resizeObserver) {
    resizeObserver.disconnect()
  }
  if (pendingRAF) {
    cancelAnimationFrame(pendingRAF)
  }
  // Reset state for potential remount
  svgInitialized = false
  parsedDates.clear()
})

// Sync dragTime with props.currentTime when it updates from parent
// (e.g., when parent loads historical scan on mount)
watch(() => props.currentTime, (newTime) => {
  if (newTime && !isDragging.value) {
    dragTime.value = newTime
  }
})

// Clear dragTime when going live
watch(() => props.showingLive, (live) => {
  if (live) {
    dragTime.value = null
  }
})

// Redraw on global tick (every 500ms) - decoupled from reactive timeline updates
watch(() => store.tick, () => {
  if (!isDragging.value) {
    scheduleDraw()
  }
})

// Redraw when selected time or live state changes
watch(() => [selectedTime.value, isLive.value], () => {
  if (!isDragging.value) {
    draw()
  }
})

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
