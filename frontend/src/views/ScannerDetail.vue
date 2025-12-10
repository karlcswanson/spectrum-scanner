<script setup>
import { onMounted, onBeforeUnmount, computed } from 'vue'
import { useRoute } from 'vue-router'
import { useScannersStore } from '../stores/scanners'
import BandChart from '../components/BandChart.vue'

const route = useRoute()
const store = useScannersStore()

const scannerId = computed(() => route.params.id)
const scanner = computed(() => store.scanners[scannerId.value])
const scannerBandScans = computed(() => store.bandScans[scannerId.value] || {})

// Get enabled bands from scanner config, sorted by frequency
const enabledBands = computed(() => {
  const bands = scanner.value?.bands || []
  return bands
    .filter(b => b.enabled)
    .sort((a, b) => (Number(a.start_hz) || 0) - (Number(b.start_hz) || 0))
})

function getScanForBand(bandName) {
  return scannerBandScans.value[bandName] || null
}

onMounted(() => {
  store.subscribe(scannerId.value)
})

onBeforeUnmount(() => {
  store.unsubscribe(scannerId.value)
})
</script>

<template>
  <div>
    <div class="mb-6">
      <router-link to="/" class="text-blue-400 hover:text-blue-300">
        &larr; Back to Dashboard
      </router-link>
    </div>

    <div v-if="scanner" class="space-y-6">
      <!-- Scanner Info -->
      <div class="bg-gray-800 rounded-lg p-6">
        <h1 class="text-2xl font-bold mb-2">{{ scanner.name }}</h1>
        <div class="text-gray-400">
          <p>Type: {{ scanner.scanner_type || scanner.type }}</p>
          <p v-if="scanner.location">Location: {{ scanner.location }}</p>
          <p>
            Status:
            <span :class="scanner.online ? 'text-green-400' : 'text-red-400'">
              {{ scanner.online ? 'Online' : 'Offline' }}
            </span>
            <span v-if="scanner.scanning" class="text-yellow-400 ml-2">
              (Scanning {{ scanner.current_band || '...' }})
            </span>
          </p>
        </div>
      </div>

      <!-- Per-Band Charts -->
      <div v-if="enabledBands.length > 0" class="space-y-6">
        <BandChart
          v-for="band in enabledBands"
          :key="band.name"
          :scanner-id="scannerId"
          :scanner-name="scanner.name"
          :band="band"
          :scan="getScanForBand(band.name)"
          :show-scanner="false"
          :show-timeline="true"
          :timeline-hours="0.167"
        />
      </div>

      <!-- No bands message -->
      <div v-else class="bg-gray-800 rounded-lg p-8 text-center text-gray-500">
        <p>No enabled bands configured for this scanner.</p>
        <p class="text-sm mt-2">Enable bands in the scanner's configuration to see spectrum data.</p>
      </div>
    </div>

    <div v-else class="text-center text-gray-500 py-8">
      Scanner not found or loading...
    </div>
  </div>
</template>
