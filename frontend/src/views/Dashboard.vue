<script setup>
import { computed, ref } from 'vue'
import { useScannersStore } from '../stores/scanners'
import { SCRUBBER_HOURS } from '../constants'
import ScannerHeader from '../components/ScannerHeader.vue'
import BandChart from '../components/BandChart.vue'
import MultiScannerChart from '../components/MultiScannerChart.vue'

const store = useScannersStore()

// Track which bands are selected for overlay comparison
// Key format: "scannerId:bandName"
const selectedBands = ref(new Set())

// Get all bands across all scanners, grouped by scanner
const scannerBands = computed(() => {
  const result = []
  for (const scanner of store.scannerList) {
    const bands = (scanner.bands || [])
      .filter(b => b.enabled)
      .sort((a, b) => (Number(a.start_hz) || 0) - (Number(b.start_hz) || 0))
      .map(band => ({
        scannerId: scanner.id,
        scannerName: scanner.name,
        bandName: band.name,
        band,
        scan: store.bandScans[scanner.id]?.[band.name] || null,
        key: `${scanner.id}:${band.name}`,
      }))

    if (bands.length > 0) {
      result.push({
        scanner,
        bands,
      })
    }
  }
  return result
})

// Flat list of all bands for easier iteration
const allBands = computed(() => {
  return scannerBands.value.flatMap(s => s.bands)
})

// Get selected bands for overlay
const selectedBandsList = computed(() => {
  return allBands.value.filter(item => selectedBands.value.has(item.key))
})

// Show overlay when 2+ bands selected
const showOverlay = computed(() => selectedBandsList.value.length >= 2)

// Calculate combined frequency range for overlay
const overlayRange = computed(() => {
  if (selectedBandsList.value.length === 0) {
    return { startHz: 470e6, stopHz: 608e6, label: 'No bands selected' }
  }

  let minHz = Infinity
  let maxHz = -Infinity

  for (const item of selectedBandsList.value) {
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

// Available scanners for overlay chart
const overlayAvailableScanners = computed(() => {
  return selectedBandsList.value.map(item => ({
    scannerId: item.scannerId,
    scannerName: item.scannerName,
    bandName: item.bandName,
  }))
})

// Selection helpers
function isSelected(key) {
  return selectedBands.value.has(key)
}

function toggleSelection(key) {
  if (selectedBands.value.has(key)) {
    selectedBands.value.delete(key)
  } else {
    selectedBands.value.add(key)
  }
  // Force reactivity
  selectedBands.value = new Set(selectedBands.value)
}

function clearSelection() {
  selectedBands.value = new Set()
}
</script>

<template>
  <div>
    <!-- Header with connection status -->
    <div class="flex items-center justify-between mb-6">
      <h1 class="text-2xl font-bold">Dashboard</h1>
      <div class="flex items-center gap-4">
        <!-- Selection info -->
        <div v-if="selectedBands.size > 0" class="flex items-center gap-2">
          <span class="text-sm text-gray-400">
            {{ selectedBands.size }} band{{ selectedBands.size > 1 ? 's' : '' }} selected
          </span>
          <button
            @click="clearSelection"
            class="text-xs text-gray-400 hover:text-white px-2 py-1 rounded bg-gray-700 hover:bg-gray-600"
          >
            Clear
          </button>
        </div>

        <!-- Error indicator -->
        <div
          v-if="store.lastError && Date.now() - store.lastError.timestamp < 10000"
          class="flex items-center space-x-2 text-red-400 text-sm"
        >
          <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
          </svg>
          <span>{{ store.lastError.message }}</span>
        </div>

        <!-- Connection status -->
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

    <!-- No scanners message -->
    <div
      v-if="store.scannerList.length === 0"
      class="text-center text-gray-500 py-12"
    >
      No scanners connected. Waiting for data...
    </div>

    <!-- Overlay comparison chart (shows when 2+ bands selected) -->
    <div v-if="showOverlay" class="mb-6">
      <div class="bg-gray-800 rounded-lg p-4">
        <div class="flex items-center justify-between mb-3">
          <h2 class="text-lg font-semibold text-cyan-400">
            Comparison
            <span class="text-gray-500 font-normal text-sm ml-2">
              {{ selectedBandsList.length }} bands
            </span>
          </h2>
          <button
            @click="clearSelection"
            class="text-sm text-gray-400 hover:text-white px-3 py-1 rounded bg-gray-700 hover:bg-gray-600"
          >
            Clear Selection
          </button>
        </div>
        <MultiScannerChart
          :start-hz="overlayRange.startHz"
          :stop-hz="overlayRange.stopHz"
          :label="overlayRange.label"
          :available-scanners="overlayAvailableScanners"
          :height="350"
        />
      </div>
    </div>

    <!-- Scanner sections -->
    <div class="space-y-6">
      <div v-for="{ scanner, bands } in scannerBands" :key="scanner.id">
        <!-- Scanner header with inline controls -->
        <ScannerHeader :scanner="scanner" class="mb-4" />

        <!-- Band charts for this scanner -->
        <div class="space-y-4">
          <BandChart
            v-for="item in bands"
            :key="item.key"
            :scanner-id="item.scannerId"
            :scanner-name="item.scannerName"
            :band="item.band"
            :scan="item.scan"
            :show-timeline="true"
            :timeline-hours="SCRUBBER_HOURS"
            :selectable="true"
            :selected="isSelected(item.key)"
            @update:selected="toggleSelection(item.key)"
          />
        </div>
      </div>

      <!-- No enabled bands message -->
      <div
        v-if="store.scannerList.length > 0 && allBands.length === 0"
        class="bg-gray-800 rounded-lg p-8 text-center text-gray-500"
      >
        No enabled bands. Configure bands in scanner settings.
      </div>
    </div>
  </div>
</template>
