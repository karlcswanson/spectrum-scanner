<script setup>
import { onMounted, onUnmounted, computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useScannersStore } from '../stores/scanners'
import { useAuthStore } from '../stores/auth'
import { SCRUBBER_HOURS } from '../constants'
import BandChart from '../components/BandChart.vue'

const route = useRoute()
const store = useScannersStore()
const auth = useAuthStore()

const scannerId = computed(() => route.params.id)
const scanner = computed(() => store.scanners[scannerId.value])

// Can the current user control this scanner?
const canWrite = computed(() => {
  if (auth.isReadonly) return false
  if (auth.isStaff) return true
  return scanner.value?.user_permission === 'rw'
})
const scannerBandScans = computed(() => store.bandScans[scannerId.value] || {})

// Get all bands from scanner config, sorted by frequency
const allBands = computed(() => {
  const bands = scanner.value?.bands || []
  return bands.sort((a, b) => (Number(a.start_hz) || 0) - (Number(b.start_hz) || 0))
})

// Get enabled bands from scanner config, sorted by frequency
const enabledBands = computed(() => {
  return allBands.value.filter(b => b.enabled)
})

// Settings from scanner config
const settings = computed(() => scanner.value?.settings || {})

// Local state for gain slider
const gainValue = ref(40)
const gainMode = ref('manual')

// Collapsible details state
const showDetails = ref(false)

function getScanForBand(bandName) {
  return scannerBandScans.value[bandName] || null
}

// Control functions
function startScanning() {
  store.sendStartCommand(scannerId.value)
}

function stopScanning() {
  store.sendStopCommand(scannerId.value)
}

function toggleBand(bandName) {
  const bands = allBands.value.map(b => ({
    ...b,
    enabled: b.name === bandName ? !b.enabled : b.enabled,
  }))
  store.sendBandsCommand(scannerId.value, bands)
}

function applyGain() {
  store.sendGainCommand(scannerId.value, gainValue.value, gainMode.value)
}

// Watch for settings changes and sync local state
watch(settings, (newSettings) => {
  if (newSettings.rx_gain !== undefined) {
    gainValue.value = newSettings.rx_gain
  }
  // Normalize gain mode to lowercase, default to 'manual' if empty
  const mode = (newSettings.rx_gain_mode || '').toLowerCase()
  gainMode.value = mode || 'manual'
}, { immediate: true })

// Subscribe to MQTT for this scanner (lazy: only while viewing)
let subscribedId = null

watch(scannerId, (newId, oldId) => {
  if (oldId) store.unsubscribe(oldId)
  if (newId) { store.subscribe(newId); subscribedId = newId }
}, { immediate: true })

onUnmounted(() => {
  if (subscribedId) store.unsubscribe(subscribedId)
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
      <!-- Scanner Info & Controls -->
      <div class="bg-gray-800 rounded-lg p-6">
        <div class="flex justify-between items-start">
          <div>
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

          <!-- Start/Stop Buttons (hidden for readonly users) -->
          <div v-if="canWrite" class="flex gap-2">
            <button
              v-if="!scanner.scanning"
              @click="startScanning"
              :disabled="!scanner.online"
              class="px-4 py-2 bg-cyan-500 hover:bg-cyan-600 disabled:bg-gray-600 disabled:cursor-not-allowed text-black font-semibold rounded"
            >
              Start Scan
            </button>
            <button
              v-else
              @click="stopScanning"
              class="px-4 py-2 bg-red-500 hover:bg-red-600 text-white font-semibold rounded"
            >
              Stop Scan
            </button>
          </div>
        </div>

        <!-- Collapsible Scanner Details -->
        <div class="mt-4 border-t border-gray-700 pt-4">
          <button
            @click="showDetails = !showDetails"
            class="flex items-center gap-2 text-gray-400 hover:text-gray-300 text-sm"
          >
            <span class="transform transition-transform" :class="showDetails ? 'rotate-90' : ''">&#9654;</span>
            Scanner Details
          </button>
          <div v-if="showDetails" class="mt-3 grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
            <div>
              <span class="text-gray-500">Scanner ID</span>
              <p class="font-mono text-xs text-gray-300 break-all">{{ scannerId }}</p>
            </div>
            <div>
              <span class="text-gray-500">Type</span>
              <p class="text-gray-300">{{ scanner.scanner_type || scanner.type || 'Unknown' }}</p>
            </div>
            <div>
              <span class="text-gray-500">Dwell Time</span>
              <p class="text-gray-300">{{ settings.dwell_time_ms || '--' }} ms</p>
            </div>
            <div>
              <span class="text-gray-500">Mode</span>
              <p class="text-gray-300">{{ settings.mode || 'Average' }}</p>
            </div>
            <div>
              <span class="text-gray-500">RX Gain</span>
              <p class="text-gray-300">{{ settings.rx_gain ?? '--' }} dB</p>
            </div>
            <div>
              <span class="text-gray-500">Gain Mode</span>
              <p class="text-gray-300">{{ settings.rx_gain_mode || 'manual' }}</p>
            </div>
            <div v-if="scanner.description" class="col-span-2">
              <span class="text-gray-500">Description</span>
              <p class="text-gray-300">{{ scanner.description }}</p>
            </div>
          </div>
        </div>
      </div>

      <!-- Band Selection (hidden for readonly users) -->
      <div v-if="canWrite && allBands.length > 0" class="bg-gray-800 rounded-lg p-6">
        <h3 class="text-lg font-semibold text-cyan-400 mb-3">Bands</h3>
        <div class="flex flex-wrap gap-3">
          <label
            v-for="band in allBands"
            :key="band.name"
            class="flex items-center gap-2 px-3 py-2 rounded cursor-pointer transition-colors"
            :class="band.enabled ? 'bg-cyan-900/50 border border-cyan-500' : 'bg-gray-700 hover:bg-gray-600'"
          >
            <input
              type="checkbox"
              :checked="band.enabled"
              @change="toggleBand(band.name)"
              class="w-4 h-4 accent-cyan-400"
            />
            <span class="font-medium">{{ band.name }}</span>
            <span class="text-gray-400 text-sm">
              ({{ (band.start_hz / 1e6).toFixed(0) }}-{{ (band.stop_hz / 1e6).toFixed(0) }} MHz)
            </span>
          </label>
        </div>
      </div>

      <!-- Gain Settings (hidden for readonly users) -->
      <div v-if="canWrite" class="bg-gray-800 rounded-lg p-6">
        <h3 class="text-lg font-semibold text-cyan-400 mb-3">Gain Settings</h3>
        <div class="space-y-4">
          <div class="flex items-center gap-4">
            <label class="text-gray-400 w-28">RX Gain (dB)</label>
            <input
              type="range"
              v-model.number="gainValue"
              min="0"
              max="73"
              class="flex-1 max-w-xs accent-cyan-400"
            />
            <input
              type="number"
              v-model.number="gainValue"
              min="0"
              max="73"
              class="w-20 px-2 py-1 bg-gray-900 border border-gray-600 rounded text-center"
            />
          </div>
          <div class="flex items-center gap-4">
            <label class="text-gray-400 w-28">Gain Mode</label>
            <select
              v-model="gainMode"
              class="flex-1 max-w-xs px-3 py-2 bg-gray-900 border border-gray-600 rounded"
            >
              <option value="manual">Manual (recommended)</option>
              <option value="slow_attack">Slow Attack (AGC)</option>
              <option value="fast_attack">Fast Attack (AGC)</option>
              <option value="hybrid">Hybrid</option>
            </select>
          </div>
          <button
            @click="applyGain"
            class="px-4 py-2 bg-cyan-500 hover:bg-cyan-600 text-black font-semibold rounded"
          >
            Apply Gain
          </button>
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
          :timeline-hours="SCRUBBER_HOURS"
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
