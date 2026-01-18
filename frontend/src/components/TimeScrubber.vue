<script setup>
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
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
  // Hide individual scan markers (density bar is usually sufficient)
  hideMarkers: {
    type: Boolean,
    default: false,
  },
  // Show data density bar
  showDensity: {
    type: Boolean,
    default: true,
  },
  // External tick for periodic redraws (standalone mode uses this instead of store.tick)
  tick: {
    type: Number,
    default: 0,
  },
})

// Time range presets
const timeRangeOptions = [
  { label: '10 min', hours: 0.167 },
  { label: '30 min', hours: 0.5 },
  { label: '1 hour', hours: 1 },
  { label: '6 hours', hours: 6 },
  { label: '24 hours', hours: 24 },
]

// Selected time range
const selectedRange = ref(props.maxHours)

// Custom date range mode
const showDatePicker = ref(false)
const customStartDate = ref('')
const customStartTime = ref('')
const customEndDate = ref('')
const customEndTime = ref('')
const isCustomRange = ref(false)
const customRangeStart = ref(null)
const customRangeEnd = ref(null)

const emit = defineEmits(['select', 'preview', 'live', 'rangeChange'])

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

// Is the display in live mode? (user hasn't selected a historical time)
// Use dragTime as the primary indicator - if null, we're in live mode
// showingLive is secondary (indicates if live data is actually available)
const isLive = computed(() => !dragTime.value)

// Store xScale for drag operations
let currentXScale = null

// Filter timeline by band if specified
const filteredTimeline = computed(() => {
  if (!props.bandName) return props.timeline
  return props.timeline.filter(t => t.band__name === props.bandName)
})

// Time range - computed fresh in draw(), using selected range
function getTimeRange() {
  if (isCustomRange.value && customRangeStart.value && customRangeEnd.value) {
    return { start: customRangeStart.value, end: customRangeEnd.value }
  }
  const now = new Date()
  const hours = selectedRange.value || props.maxHours
  const start = new Date(now.getTime() - hours * 60 * 60 * 1000)
  return { start, end: now }
}

// Handle time range selection (preset)
function setTimeRange(hours) {
  isCustomRange.value = false
  customRangeStart.value = null
  customRangeEnd.value = null
  selectedRange.value = hours
  emit('rangeChange', { hours })
  scheduleDraw()
}

// Toggle date picker
function toggleDatePicker() {
  showDatePicker.value = !showDatePicker.value
  if (showDatePicker.value) {
    // Set default values to today
    const now = new Date()
    const yesterday = new Date(now.getTime() - 24 * 60 * 60 * 1000)
    customEndDate.value = now.toISOString().split('T')[0]
    customEndTime.value = now.toTimeString().slice(0, 5)
    customStartDate.value = yesterday.toISOString().split('T')[0]
    customStartTime.value = yesterday.toTimeString().slice(0, 5)
  }
}

// Apply custom date range
function applyCustomRange() {
  const start = new Date(`${customStartDate.value}T${customStartTime.value}`)
  const end = new Date(`${customEndDate.value}T${customEndTime.value}`)

  if (isNaN(start.getTime()) || isNaN(end.getTime())) {
    console.error('Invalid date range')
    return
  }

  isCustomRange.value = true
  customRangeStart.value = start
  customRangeEnd.value = end
  selectedRange.value = null
  showDatePicker.value = false

  emit('rangeChange', { start, end })
  scheduleDraw()
}

// Format custom range for display
const customRangeDisplay = computed(() => {
  if (!isCustomRange.value || !customRangeStart.value) return null
  const opts = { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }
  return `${customRangeStart.value.toLocaleDateString('en-US', opts)} - ${customRangeEnd.value.toLocaleDateString('en-US', opts)}`
})

function goLive() {
  dragTime.value = null
  emit('live')
}

// Pixel-to-scan index for O(1) lookup during drag
let pixelIndex = new Map() // pixel x -> marker

function buildPixelIndex(markers, xScale) {
  pixelIndex.clear()
  for (const marker of markers) {
    const px = Math.round(xScale(marker.date))
    // Keep the marker closest to this pixel
    if (!pixelIndex.has(px)) {
      pixelIndex.set(px, marker)
    }
  }
}

// Find scan at pixel position - O(1) with small search radius
function findScanAtPixel(x) {
  // Check exact pixel first
  if (pixelIndex.has(x)) return pixelIndex.get(x)
  // Search within 3 pixels
  for (let offset = 1; offset <= 3; offset++) {
    if (pixelIndex.has(x - offset)) return pixelIndex.get(x - offset)
    if (pixelIndex.has(x + offset)) return pixelIndex.get(x + offset)
  }
  return null
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

    svg.select('.chart').append('g').attr('class', 'density-bar')
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

  // Draw density bar to show data availability
  if (props.showDensity) {
    const densityBar = chart.select('.density-bar')
    densityBar.selectAll('*').remove()

    // Create bins for density calculation
    const numBins = Math.min(plotWidth / 4, 100) // 4px per bin minimum
    const binWidth = plotWidth / numBins
    const bins = new Array(numBins).fill(0)

    // Count scans in each bin
    filteredTimeline.value.forEach(t => {
      const date = getDate(t.timestamp)
      if (date >= timeRange.start && date <= timeRange.end) {
        const x = xScale(date)
        const binIdx = Math.min(Math.floor(x / binWidth), numBins - 1)
        if (binIdx >= 0) bins[binIdx]++
      }
    })

    // Find max for normalization
    const maxCount = Math.max(...bins, 1)

    // Draw density rectangles
    const barHeight = 6
    bins.forEach((count, idx) => {
      if (count > 0) {
        const intensity = Math.min(count / maxCount, 1)
        densityBar.append('rect')
          .attr('x', idx * binWidth)
          .attr('y', plotHeight - barHeight - 2)
          .attr('width', binWidth - 1)
          .attr('height', barHeight)
          .attr('fill', `rgba(34, 197, 94, ${0.3 + intensity * 0.7})`)
          .attr('rx', 1)
      }
    })
  }

  // Get markers with cached dates (needed for drag operations even if not drawn)
  const allMarkers = filteredTimeline.value
    .map(t => ({
      ...t,
      date: getDate(t.timestamp),
    }))
    .filter(t => t.date >= timeRange.start && t.date <= timeRange.end)

  // Build pixel index for O(1) lookup during drag
  buildPixelIndex(allMarkers, xScale)

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

    // Update markers efficiently - smaller and dimmer to complement density bar
    const markerRadius = 2
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
        return '#4a556880' // dimmer gray with transparency
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

        // O(1) pixel lookup for scan
        const closest = findScanAtPixel(Math.round(x))
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
        const closest = findScanAtPixel(Math.round(x))
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
        const closest = findScanAtPixel(Math.round(x))
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

// Note: dragTime is cleared directly in goLive(), no watcher needed

// Redraw on tick prop change (for periodic updates)
watch(() => props.tick, () => {
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
  <div class="time-scrubber bg-gray-900 rounded p-2 relative">
    <div class="flex items-center justify-between mb-2">
      <div class="text-xs text-gray-500">
        <span v-if="isLive" class="text-green-400 font-semibold">● LIVE</span>
        <span v-else-if="isCustomRange" class="text-purple-400">{{ customRangeDisplay }}</span>
        <span v-else class="text-yellow-400">{{ selectedTimeDisplay }}</span>
      </div>
      <div class="flex items-center gap-2">
        <!-- Time range selector -->
        <div class="flex items-center gap-1 border-r border-gray-700 pr-2 mr-1">
          <button
            v-for="opt in timeRangeOptions"
            :key="opt.hours"
            @click="setTimeRange(opt.hours)"
            class="px-2 py-0.5 rounded text-xs transition-colors"
            :class="selectedRange === opt.hours && !isCustomRange
              ? 'bg-cyan-600 text-white'
              : 'bg-gray-800 hover:bg-gray-700 text-gray-400'"
          >
            {{ opt.label }}
          </button>
          <button
            @click="toggleDatePicker"
            class="px-2 py-0.5 rounded text-xs transition-colors"
            :class="isCustomRange
              ? 'bg-purple-600 text-white'
              : 'bg-gray-800 hover:bg-gray-700 text-gray-400'"
          >
            Custom
          </button>
        </div>
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

    <!-- Custom date range picker -->
    <div
      v-if="showDatePicker"
      class="absolute top-full left-0 right-0 mt-1 bg-gray-800 border border-gray-700 rounded-lg p-3 z-50 shadow-xl"
    >
      <div class="text-xs text-gray-400 mb-2 font-semibold">Custom Date Range</div>
      <div class="flex items-center gap-4">
        <div class="flex-1">
          <label class="text-xs text-gray-500 block mb-1">Start</label>
          <div class="flex gap-1">
            <input
              v-model="customStartDate"
              type="date"
              class="bg-gray-700 text-white text-xs rounded px-2 py-1 w-28"
            />
            <input
              v-model="customStartTime"
              type="time"
              class="bg-gray-700 text-white text-xs rounded px-2 py-1 w-20"
            />
          </div>
        </div>
        <div class="text-gray-600">→</div>
        <div class="flex-1">
          <label class="text-xs text-gray-500 block mb-1">End</label>
          <div class="flex gap-1">
            <input
              v-model="customEndDate"
              type="date"
              class="bg-gray-700 text-white text-xs rounded px-2 py-1 w-28"
            />
            <input
              v-model="customEndTime"
              type="time"
              class="bg-gray-700 text-white text-xs rounded px-2 py-1 w-20"
            />
          </div>
        </div>
        <div class="flex gap-2">
          <button
            @click="applyCustomRange"
            class="px-3 py-1 bg-purple-600 hover:bg-purple-500 text-white text-xs rounded font-semibold"
          >
            Apply
          </button>
          <button
            @click="showDatePicker = false"
            class="px-3 py-1 bg-gray-700 hover:bg-gray-600 text-gray-300 text-xs rounded"
          >
            Cancel
          </button>
        </div>
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
