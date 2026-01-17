<script setup>
import { ref, computed, watch } from 'vue'
import { useScannersStore } from '../stores/scanners'
import { useAuthStore } from '../stores/auth'

const props = defineProps({
  scanner: {
    type: Object,
    required: true,
  },
})

const store = useScannersStore()
const auth = useAuthStore()

// Collapsible settings state
const showSettings = ref(false)

// Local state for gain controls
const gainValue = ref(40)
const gainMode = ref('manual')

// Get settings from scanner
const settings = computed(() => props.scanner?.settings || {})
const allBands = computed(() => {
  const bands = props.scanner?.bands || []
  return bands.sort((a, b) => (Number(a.start_hz) || 0) - (Number(b.start_hz) || 0))
})

// Status helpers
const statusColor = computed(() => {
  if (!props.scanner.online) return 'bg-red-500'
  if (props.scanner.scanning) return 'bg-green-500'
  return 'bg-yellow-500'
})

const statusText = computed(() => {
  if (!props.scanner.online) return 'Offline'
  if (props.scanner.scanning) return 'Scanning'
  return 'Idle'
})

// Control functions
function startScanning() {
  store.sendStartCommand(props.scanner.id)
}

function stopScanning() {
  store.sendStopCommand(props.scanner.id)
}

function toggleBand(bandName) {
  const bands = allBands.value.map(b => ({
    ...b,
    enabled: b.name === bandName ? !b.enabled : b.enabled,
  }))
  store.sendBandsCommand(props.scanner.id, bands)
}

function applyGain() {
  store.sendGainCommand(props.scanner.id, gainValue.value, gainMode.value)
}

// Sync local state with scanner settings
watch(settings, (newSettings) => {
  if (newSettings.rx_gain !== undefined) {
    gainValue.value = newSettings.rx_gain
  }
  const mode = (newSettings.rx_gain_mode || '').toLowerCase()
  gainMode.value = mode || 'manual'
}, { immediate: true })
</script>

<template>
  <div class="bg-gray-800 rounded-lg overflow-hidden">
    <!-- Main header bar -->
    <div class="p-4 flex items-center justify-between">
      <div class="flex items-center gap-4">
        <!-- Scanner name as link to detail page -->
        <router-link
          :to="`/scanner/${scanner.id}`"
          class="text-lg font-semibold hover:text-cyan-400 transition-colors"
        >
          {{ scanner.name }}
        </router-link>
        <span v-if="scanner.location" class="text-gray-400 text-sm">
          {{ scanner.location }}
        </span>
        <!-- Status badge -->
        <div class="flex items-center gap-2">
          <span class="w-2 h-2 rounded-full" :class="statusColor"></span>
          <span class="text-sm text-gray-400">{{ statusText }}</span>
          <span v-if="scanner.scanning && scanner.current_band" class="text-sm text-gray-500">
            ({{ scanner.current_band }})
          </span>
        </div>
      </div>

      <div class="flex items-center gap-3">
        <!-- Start/Stop button (hidden for readonly) -->
        <template v-if="!auth.isReadonly">
          <button
            v-if="!scanner.scanning"
            @click="startScanning"
            :disabled="!scanner.online"
            class="px-3 py-1.5 bg-cyan-500 hover:bg-cyan-600 disabled:bg-gray-600 disabled:cursor-not-allowed text-black text-sm font-semibold rounded"
          >
            Start
          </button>
          <button
            v-else
            @click="stopScanning"
            class="px-3 py-1.5 bg-red-500 hover:bg-red-600 text-white text-sm font-semibold rounded"
          >
            Stop
          </button>
        </template>

        <!-- Settings toggle -->
        <button
          v-if="!auth.isReadonly"
          @click="showSettings = !showSettings"
          class="p-2 rounded hover:bg-gray-700 transition-colors"
          :class="showSettings ? 'text-cyan-400' : 'text-gray-400'"
          title="Scanner settings"
        >
          <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
          </svg>
        </button>
      </div>
    </div>

    <!-- Collapsible settings panel -->
    <div v-if="showSettings && !auth.isReadonly" class="border-t border-gray-700 p-4 bg-gray-850">
      <div class="grid md:grid-cols-2 gap-6">
        <!-- Bands section -->
        <div>
          <h4 class="text-sm font-medium text-gray-300 mb-3">Bands</h4>
          <div class="flex flex-wrap gap-2">
            <label
              v-for="band in allBands"
              :key="band.name"
              class="flex items-center gap-2 px-3 py-1.5 rounded cursor-pointer text-sm transition-colors"
              :class="band.enabled
                ? 'bg-cyan-900/50 border border-cyan-500 text-cyan-300'
                : 'bg-gray-700 hover:bg-gray-600 text-gray-300 border border-transparent'"
            >
              <input
                type="checkbox"
                :checked="band.enabled"
                @change="toggleBand(band.name)"
                class="w-3.5 h-3.5 accent-cyan-400"
              />
              <span>{{ band.name }}</span>
            </label>
          </div>
        </div>

        <!-- Gain section -->
        <div>
          <h4 class="text-sm font-medium text-gray-300 mb-3">Gain</h4>
          <div class="space-y-3">
            <div class="flex items-center gap-3">
              <input
                type="range"
                v-model.number="gainValue"
                min="0"
                max="73"
                class="flex-1 accent-cyan-400"
              />
              <input
                type="number"
                v-model.number="gainValue"
                min="0"
                max="73"
                class="w-16 px-2 py-1 bg-gray-900 border border-gray-600 rounded text-center text-sm"
              />
              <span class="text-gray-400 text-sm">dB</span>
            </div>
            <div class="flex items-center gap-3">
              <select
                v-model="gainMode"
                class="flex-1 px-2 py-1.5 bg-gray-900 border border-gray-600 rounded text-sm"
              >
                <option value="manual">Manual</option>
                <option value="slow_attack">Slow Attack</option>
                <option value="fast_attack">Fast Attack</option>
                <option value="hybrid">Hybrid</option>
              </select>
              <button
                @click="applyGain"
                class="px-3 py-1.5 bg-cyan-500 hover:bg-cyan-600 text-black text-sm font-medium rounded"
              >
                Apply
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.bg-gray-850 {
  background-color: rgb(30, 34, 44);
}
</style>
