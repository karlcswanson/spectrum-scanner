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

  // Draw time axis
  const tickCount = Math.min(12, Math.floor(plotWidth / 80))
  const xAxis = d3.axisBottom(xScale)
    .ticks(tickCount)
    .tickFormat(d => {
      const hours = d.getHours()
      const minutes = d.getMinutes()
      if (minutes === 0) {
        return d3.timeFormat('%H:%M')(d)
      }
      return d3.timeFormat('%H:%M')(d)
    })

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

  // Group nearby markers to avoid overlap
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
    .attr('cursor', 'pointer')
    .on('click', (event, d) => {
      selectTime(d.date)
    })

  // Draw selected time indicator
  if (selectedTime.value) {
    const x = xScale(selectedTime.value)
    if (x >= 0 && x <= plotWidth) {
      chart.append('line')
        .attr('x1', x)
        .attr('y1', 0)
        .attr('x2', x)
        .attr('y2', plotHeight)
        .attr('stroke', '#00d4ff')
        .attr('stroke-width', 2)
    }
  }

  // Draw "now" indicator
  const nowX = xScale(new Date())
  chart.append('line')
    .attr('x1', nowX)
    .attr('y1', 0)
    .attr('x2', nowX)
    .attr('y2', plotHeight)
    .attr('stroke', isLive.value ? '#22c55e' : '#666')
    .attr('stroke-width', 1)
    .attr('stroke-dasharray', '4,2')

  // Click anywhere on timeline to seek
  chart.append('rect')
    .attr('width', plotWidth)
    .attr('height', plotHeight)
    .attr('fill', 'transparent')
    .attr('cursor', 'pointer')
    .on('click', (event) => {
      const [x] = d3.pointer(event)
      const time = xScale.invert(x)

      // Find closest scan to clicked time
      let closest = null
      let closestDiff = Infinity
      for (const marker of markers) {
        const diff = Math.abs(marker.date - time)
        if (diff < closestDiff) {
          closestDiff = diff
          closest = marker
        }
      }

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

watch(() => [props.timeline, selectedTime.value, isLive.value], draw, { deep: true })

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
