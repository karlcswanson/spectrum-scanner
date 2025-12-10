<script setup>
import { computed } from 'vue'
import { useScannersStore } from '../stores/scanners'
import ScannerCard from '../components/ScannerCard.vue'
import BandChart from '../components/BandChart.vue'

const store = useScannersStore()

// Get all bands across all scanners for display, sorted by frequency
const allBands = computed(() => {
  const bands = []
  for (const scanner of store.scannerList) {
    const scannerBands = scanner.bands || []
    for (const band of scannerBands) {
      if (band.enabled) {
        bands.push({
          scannerId: scanner.id,
          scannerName: scanner.name,
          band,
          scan: store.bandScans[scanner.id]?.[band.name] || null,
        })
      }
    }
  }
  // Sort by start frequency (lowest first)
  return bands.sort((a, b) => (Number(a.band.start_hz) || 0) - (Number(b.band.start_hz) || 0))
})
</script>

<template>
  <div>
    <div class="flex items-center justify-between mb-6">
      <h1 class="text-2xl font-bold">Dashboard</h1>
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

    <!-- Per-band spectrum displays -->
    <div class="space-y-6">
      <BandChart
        v-for="item in allBands"
        :key="`${item.scannerId}-${item.band.name}`"
        :scanner-id="item.scannerId"
        :scanner-name="item.scannerName"
        :band="item.band"
        :scan="item.scan"
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
