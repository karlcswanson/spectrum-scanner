<script setup>
import { computed, ref } from 'vue'
import { useScannersStore } from '../stores/scanners'
import ScannerCard from '../components/ScannerCard.vue'
import BandChart from '../components/BandChart.vue'
import MultiScannerChart from '../components/MultiScannerChart.vue'

const store = useScannersStore()

// View mode: 'separate' shows individual charts (default), 'combined' shows overlay
const viewMode = ref('separate')

// Track which scanners/bands are selected for the combined view (starts empty)
const selectedScanners = ref(new Set())

// Get all bands across all scanners
const allBands = computed(() => {
  const bands = []
  for (const scanner of store.scannerList) {
    const scannerBands = scanner.bands || []
    for (const band of scannerBands) {
      if (band.enabled) {
        bands.push({
          scannerId: scanner.id,
          scannerName: scanner.name,
          bandName: band.name,
          band,
          scan: store.bandScans[scanner.id]?.[band.name] || null,
        })
      }
    }
  }
  return bands.sort((a, b) => (Number(a.band.start_hz) || 0) - (Number(b.band.start_hz) || 0))
})

// Group bands by scanner for the selection UI
const bandsByScanner = computed(() => {
  const grouped = {}
  for (const item of allBands.value) {
    if (!grouped[item.scannerId]) {
      grouped[item.scannerId] = {
        scannerId: item.scannerId,
        scannerName: item.scannerName,
        bands: [],
      }
    }
    grouped[item.scannerId].bands.push(item)
  }
  return Object.values(grouped)
})

// Get selected bands for the combined chart
const selectedBands = computed(() => {
  return allBands.value.filter(item => {
    const key = `${item.scannerId}:${item.bandName}`
    return selectedScanners.value.has(key)
  })
})

// Calculate the combined frequency range from all selected scanners
const combinedRange = computed(() => {
  if (selectedBands.value.length === 0) {
    return { startHz: 470e6, stopHz: 608e6, label: 'No scanners selected' }
  }

  let minHz = Infinity
  let maxHz = -Infinity

  for (const item of selectedBands.value) {
    const startHz = Number(item.band.start_hz) || 0
    const stopHz = Number(item.band.stop_hz) || 0
    if (startHz && stopHz) {
      minHz = Math.min(minHz, startHz)
      maxHz = Math.max(maxHz, stopHz)
    }
  }

  const startMHz = (minHz / 1e6).toFixed(0)
  const stopMHz = (maxHz / 1e6).toFixed(0)

  return {
    startHz: minHz,
    stopHz: maxHz,
    label: `${startMHz}-${stopMHz} MHz`,
  }
})

// Available scanners for the MultiScannerChart
const availableScanners = computed(() => {
  return selectedBands.value.map(item => ({
    scannerId: item.scannerId,
    scannerName: item.scannerName,
    bandName: item.bandName,
  }))
})

// Toggle scanner selection
function toggleScanner(scannerId, bandName) {
  const key = `${scannerId}:${bandName}`
  if (selectedScanners.value.has(key)) {
    selectedScanners.value.delete(key)
  } else {
    selectedScanners.value.add(key)
  }
  // Force reactivity
  selectedScanners.value = new Set(selectedScanners.value)
}

function isSelected(scannerId, bandName) {
  return selectedScanners.value.has(`${scannerId}:${bandName}`)
}

function selectAll() {
  allBands.value.forEach(item => {
    selectedScanners.value.add(`${item.scannerId}:${item.bandName}`)
  })
  selectedScanners.value = new Set(selectedScanners.value)
}

function selectNone() {
  selectedScanners.value.clear()
  selectedScanners.value = new Set(selectedScanners.value)
}
</script>

<template>
  <div>
    <div class="flex items-center justify-between mb-6">
      <h1 class="text-2xl font-bold">Dashboard</h1>
      <div class="flex items-center gap-4">
        <!-- Overlay mode toggle -->
        <button
          @click="viewMode = viewMode === 'separate' ? 'combined' : 'separate'"
          class="px-3 py-1.5 rounded text-sm transition-colors flex items-center gap-2"
          :class="viewMode === 'combined'
            ? 'bg-cyan-500 text-black font-semibold'
            : 'bg-gray-700 text-gray-300 hover:bg-gray-600'"
        >
          <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 8V4m0 0h4M4 4l5 5m11-1V4m0 0h-4m4 0l-5 5M4 16v4m0 0h4m-4 0l5-5m11 5l-5-5m5 5v-4m0 4h-4" />
          </svg>
          Overlay
        </button>

        <div class="flex items-center space-x-2">
          <span
            class="w-3 h-3 rounded-full"
            :class="store.connected ? 'bg-green-500' : 'bg-red-500'"
          ></span>
          <span class="text-sm text-gray-400">
            {{ store.connected ? 'Connected' : 'Disconnected' }}
          </span>
        </div>
      </div>
    </div>

    <!-- Scanner cards -->
    <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 mb-8">
      <ScannerCard
        v-for="scanner in store.scannerList"
        :key="scanner.id"
        :scanner="scanner"
      />

      <div
        v-if="store.scannerList.length === 0"
        class="col-span-full text-center text-gray-500 py-8"
      >
        No scanners connected. Waiting for data...
      </div>
    </div>

    <!-- Combined view: All selected scanners on one chart -->
    <div v-if="viewMode === 'combined'" class="space-y-4">
      <!-- Scanner/Band selection panel -->
      <div class="bg-gray-800 rounded-lg p-4">
        <div class="flex items-center justify-between mb-3">
          <h3 class="text-sm font-semibold text-gray-300">Select Bands to Display</h3>
          <div class="flex gap-2">
            <button
              @click="selectAll"
              class="px-2 py-1 text-xs bg-gray-700 hover:bg-gray-600 rounded text-gray-300"
            >
              All
            </button>
            <button
              @click="selectNone"
              class="px-2 py-1 text-xs bg-gray-700 hover:bg-gray-600 rounded text-gray-300"
            >
              None
            </button>
          </div>
        </div>

        <!-- Group by scanner -->
        <div class="space-y-3">
          <div
            v-for="scanner in bandsByScanner"
            :key="scanner.scannerId"
            class="flex flex-wrap items-center gap-2"
          >
            <span class="text-xs text-gray-400 w-28 truncate" :title="scanner.scannerName">
              {{ scanner.scannerName }}:
            </span>
            <button
              v-for="item in scanner.bands"
              :key="item.bandName"
              @click="toggleScanner(item.scannerId, item.bandName)"
              class="px-3 py-1 rounded text-xs font-medium transition-all border"
              :class="isSelected(item.scannerId, item.bandName)
                ? 'bg-cyan-500 border-cyan-500 text-black'
                : 'border-gray-600 bg-transparent text-gray-400 hover:border-gray-500'"
            >
              {{ item.bandName }}
              <span class="opacity-60 ml-1">
                ({{ (item.band.start_hz / 1e6).toFixed(0) }}-{{ (item.band.stop_hz / 1e6).toFixed(0) }})
              </span>
            </button>
          </div>
        </div>

        <p v-if="bandsByScanner.length === 0" class="text-gray-500 text-sm">
          No scanners available
        </p>
      </div>

      <!-- Combined spectrum chart -->
      <MultiScannerChart
        v-if="selectedBands.length > 0"
        :start-hz="combinedRange.startHz"
        :stop-hz="combinedRange.stopHz"
        :label="combinedRange.label"
        :available-scanners="availableScanners"
        :height="400"
      />

      <div
        v-else-if="store.scannerList.length > 0"
        class="bg-gray-800 rounded-lg p-8 text-center text-gray-500"
      >
        Select bands above to display spectrum data
      </div>
    </div>

    <!-- Separate view: Individual charts per scanner/band -->
    <div v-else class="space-y-6">
      <BandChart
        v-for="item in allBands"
        :key="`${item.scannerId}-${item.band.name}`"
        :scanner-id="item.scannerId"
        :scanner-name="item.scannerName"
        :band="item.band"
        :scan="item.scan"
        :show-timeline="true"
        :timeline-hours="0.167"
      />

      <div
        v-if="allBands.length === 0 && store.scannerList.length > 0"
        class="bg-gray-800 rounded-lg p-8 text-center text-gray-500"
      >
        Waiting for scan data...
      </div>
    </div>
  </div>
</template>
