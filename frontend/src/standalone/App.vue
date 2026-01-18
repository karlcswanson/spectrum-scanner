<script setup>
import { onMounted, onUnmounted, ref, computed } from 'vue'
import { useStandaloneStore, scanBus } from './store'
import BandCard from '../components/BandCard.vue'
import ScannerSettings from '../components/ScannerSettings.vue'

const store = useStandaloneStore()

// Reactive error display (updates every second instead of every render)
const now = ref(Date.now())
let nowInterval = null

const showError = computed(() => {
  return store.lastError && (now.value - store.lastError.timestamp) < 10000
})

// UI state
const showSettings = ref(false)

// Connect on mount
onMounted(() => {
  nowInterval = setInterval(() => {
    now.value = Date.now()
  }, 1000)
  store.connect()
})

onUnmounted(() => {
  if (nowInterval) clearInterval(nowInterval)
  store.disconnect()
})

// Export handler for BandCard
function handleExport(bandName) {
  store.downloadCSV(bandName, store.config?.name)
}

// Settings handlers
function handleUpdateName(name) {
  store.updateName(name)
}

function handleUpdateGain(value, mode) {
  store.updateGain(value, mode)
}

function handleToggleBand(bandName) {
  store.toggleBand(bandName)
}
</script>

<template>
  <div class="min-h-screen bg-gray-900 text-white">
    <!-- Header -->
    <header class="bg-gray-800 border-b border-gray-700 px-6 py-4">
      <div class="flex items-center justify-between">
        <div class="flex items-center gap-4">
          <img src="/logo.png" alt="Spectrum Scanner" class="h-8 w-8" />
          <h1 class="text-xl font-bold text-white">Spectrum Scanner</h1>
          <span v-if="store.config?.name && store.config.name !== 'Spectrum Scanner'" class="text-gray-400">
            {{ store.config.name }}
          </span>
        </div>

        <div class="flex items-center gap-4">
          <!-- Error indicator -->
          <div
            v-if="showError"
            class="flex items-center gap-2 text-red-400 text-sm"
          >
            <span>{{ store.lastError.message }}</span>
          </div>

          <!-- Tuner status - clickable to open settings -->
          <button @click="showSettings = !showSettings"
               class="flex items-center gap-2 px-3 py-1.5 rounded bg-gray-700 hover:bg-gray-600 transition-colors"
          >
            <span
              class="w-2 h-2 rounded-full"
              :class="store.connected ? 'bg-green-500' : 'bg-red-500'"
            ></span>
            <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4 text-gray-300" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                 stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <circle cx="12" cy="12" r="2"></circle>
              <path d="M16.24 7.76a6 6 0 0 1 0 8.49m-8.48-.01a6 6 0 0 1 0-8.49m11.31-2.82a10 10 0 0 1 0 14.14m-14.14 0a10 10 0 0 1 0-14.14"></path>
            </svg>
            <span class="text-xs text-gray-300">Tuner</span>
          </button>

          <!-- Start/Stop -->
          <button
            v-if="!store.scanning"
            @click="store.startScanning"
            class="px-4 py-2 bg-cyan-500 hover:bg-cyan-600 text-black font-semibold rounded"
          >
            Start
          </button>
          <button
            v-else
            @click="store.stopScanning"
            class="px-4 py-2 bg-red-500 hover:bg-red-600 text-white font-semibold rounded"
          >
            Stop
          </button>
        </div>
      </div>

      <!-- Settings panel -->
      <div v-if="showSettings" class="mt-4 pt-4 border-t border-gray-700">
        <div class="flex justify-between items-center mb-4">
          <h3 class="text-sm font-medium text-gray-300">Scanner Settings</h3>
          <button
            @click="showSettings = false"
            class="p-1 rounded hover:bg-gray-700 text-gray-400 hover:text-white"
          >
            <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <line x1="18" y1="6" x2="6" y2="18"></line>
              <line x1="6" y1="6" x2="18" y2="18"></line>
            </svg>
          </button>
        </div>

        <ScannerSettings
          :config="store.config"
          :bands="store.bands"
          :settings="store.settings"
          @update:name="handleUpdateName"
          @update:gain="handleUpdateGain"
          @toggle-band="handleToggleBand"
        />
      </div>
    </header>

    <!-- Main content -->
    <main class="p-6">
      <!-- No bands message -->
      <div
        v-if="store.enabledBands.length === 0"
        class="text-center text-gray-500 py-12"
      >
        No bands enabled. Configure bands in settings.
      </div>

      <!-- Band charts -->
      <div class="space-y-6">
        <BandCard
          v-for="band in store.enabledBands"
          :key="band.name"
          :band="band"
          :scan-bus="scanBus"
          :get-scan-data="store.getScanData"
          :get-scan-info="store.getScanInfo"
          :scan-update-count="store.scanUpdateCount"
          :on-export="handleExport"
        />
      </div>
    </main>
  </div>
</template>
