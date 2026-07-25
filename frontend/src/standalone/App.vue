<script setup>
import { onMounted, onUnmounted, ref, computed, watch } from 'vue'
import { useStandaloneStore, scanBus } from './store'
import BandCard from '../components/BandCard.vue'
import ScannerSettings from '../components/ScannerSettings.vue'

const store = useStandaloneStore()

// Detect Wails environment
const isWails = !!(window.wails || window.go)

// Reactive error display (updates every second instead of every render)
const now = ref(Date.now())
let nowInterval = null

const showError = computed(() => {
  return store.lastError && (now.value - store.lastError.timestamp) < 10000
})

// UI state
const showSettings = ref(false)
const settingsTab = ref('scanner') // 'scanner' or 'server'

// Server mode form fields
const mqttBroker = ref('')
const mqttId = ref('')
const mqttToken = ref('')
const webPort = ref(8080)

// Sync MQTT config from store
watch(() => store.mqttConfig, (cfg) => {
  if (cfg) {
    mqttBroker.value = cfg.broker || ''
    mqttId.value = cfg.id || ''
    mqttToken.value = cfg.token || ''
  }
}, { immediate: true })

// Sync web config from store
watch(() => store.webConfig, (cfg) => {
  if (cfg) {
    webPort.value = cfg.port || 8080
  }
}, { immediate: true })

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

// Export handler for BandCard - uses native dialog in Wails, browser download otherwise
async function handleExport(bandName) {
  const csv = store.generateCSV(bandName)
  if (!csv) return

  // In Wails, use native file dialog
  if (isWails && window.go?.main?.App?.SaveCSV) {
    const timestamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19)
    const filename = `scan_${bandName.replace(/\s+/g, '-')}_${timestamp}.csv`
    try {
      await window.go.main.App.SaveCSV(csv, filename)
    } catch (err) {
      // Error handled by native dialog
    }
  } else {
    // Browser download
    store.downloadCSV(bandName, store.config?.device_id)
  }
}

// Settings handlers
function handleUpdateGain(value, mode) {
  store.updateGain(value, mode)
}

function handleToggleBand(bandName) {
  store.toggleBand(bandName)
}

// Server mode functions
async function saveMQTTConfig() {
  await store.setMQTTConfig({
    enabled: store.mqttConfig?.enabled || false,
    broker: mqttBroker.value,
    id: mqttId.value,
    token: mqttToken.value,
  })
}

async function saveWebConfig() {
  await store.setWebConfig({
    enabled: store.webConfig?.enabled || false,
    port: webPort.value,
  })
}

async function toggleMQTT() {
  // Toggle based on config enabled state, not connection status
  if (store.mqttConfig?.enabled) {
    await store.disableMQTT()
  } else {
    await store.enableMQTT()
  }
}

async function toggleWebServer() {
  // Toggle based on config enabled state, not connection status
  if (store.webConfig?.enabled) {
    await store.disableWebServer()
  } else {
    await store.enableWebServer()
  }
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
          <span v-if="store.config?.device_id" class="text-gray-400 font-mono text-sm">
            {{ store.config.device_id.slice(0, 8) }}
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

          <!-- Tuner status - clickable to open scanner settings -->
          <button @click="showSettings = true; settingsTab = 'scanner'"
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

          <!-- Server status - clickable to open server settings (desktop only) -->
          <button v-if="isWails"
               @click="showSettings = true; settingsTab = 'server'"
               class="flex items-center gap-2 px-3 py-1.5 rounded bg-gray-700 hover:bg-gray-600 transition-colors"
          >
            <!-- Spinner when pending -->
            <svg v-if="store.serverStatus?.mqtt === 'pending'" class="w-2 h-2 animate-spin text-cyan-400" viewBox="0 0 24 24" fill="none">
              <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
              <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
            </svg>
            <span v-else
              class="w-2 h-2 rounded-full"
              :class="{
                'bg-green-500': store.serverStatus?.mqtt === 'connected',
                'bg-red-500': store.serverStatus?.mqtt === 'error',
                'bg-gray-500': store.serverStatus?.mqtt === 'disconnected'
              }"
            ></span>
            <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4 text-gray-300" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                 stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <rect x="2" y="2" width="20" height="8" rx="2" ry="2"></rect>
              <rect x="2" y="14" width="20" height="8" rx="2" ry="2"></rect>
              <line x1="6" y1="6" x2="6.01" y2="6"></line>
              <line x1="6" y1="18" x2="6.01" y2="18"></line>
            </svg>
            <span class="text-xs text-gray-300">Server</span>
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
          <h3 class="text-sm font-medium text-gray-300">
            {{ settingsTab === 'scanner' ? 'Scanner Settings' : 'Server Settings' }}
          </h3>
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

        <!-- Scanner settings -->
        <ScannerSettings
          v-if="settingsTab === 'scanner'"
          :bands="store.bands"
          :settings="store.settings"
          @update:gain="handleUpdateGain"
          @toggle-band="handleToggleBand"
        />

        <!-- Server mode settings -->
        <div v-if="settingsTab === 'server'" class="space-y-6">
          <div class="grid md:grid-cols-2 gap-6">
            <!-- MQTT Configuration -->
            <div class="bg-gray-900 rounded-lg p-4">
              <div class="flex items-center justify-between mb-4">
                <h4 class="text-sm font-medium text-gray-300">MQTT (Spectrum Server)</h4>
                <div class="flex items-center gap-3">
                  <div class="flex items-center gap-2">
                    <!-- Spinner when pending -->
                    <svg v-if="store.serverStatus?.mqtt === 'pending'" class="w-3 h-3 animate-spin text-cyan-400" viewBox="0 0 24 24" fill="none">
                      <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                      <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
                    </svg>
                    <span v-else
                      class="w-2 h-2 rounded-full"
                      :class="{
                        'bg-green-500': store.serverStatus?.mqtt === 'connected',
                        'bg-red-500': store.serverStatus?.mqtt === 'error',
                        'bg-gray-500': store.serverStatus?.mqtt === 'disconnected'
                      }"
                    ></span>
                    <span class="text-xs text-gray-400">
                      {{ store.serverStatus?.mqtt === 'pending' ? 'Connecting...' :
                         store.serverStatus?.mqtt === 'connected' ? 'Connected' :
                         store.serverStatus?.mqtt === 'error' ? 'Error' : 'Disconnected' }}
                    </span>
                  </div>
                  <!-- Enable/Disable toggle switch -->
                  <button
                    @click="toggleMQTT"
                    :disabled="store.serverStatus?.mqtt === 'pending'"
                    class="relative w-10 h-5 rounded-full transition-colors focus:outline-none focus:ring-2 focus:ring-cyan-500/50"
                    :class="store.serverStatus?.mqtt === 'pending'
                      ? 'bg-gray-600 cursor-wait'
                      : store.mqttConfig?.enabled
                        ? 'bg-cyan-500'
                        : 'bg-gray-600'"
                  >
                    <span
                      class="absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform"
                      :class="store.mqttConfig?.enabled ? 'translate-x-5' : 'translate-x-0'"
                    ></span>
                  </button>
                </div>
              </div>

              <div class="space-y-3">
                <div>
                  <label class="block text-xs text-gray-400 mb-1">Broker URL</label>
                  <input
                    v-model="mqttBroker"
                    type="text"
                    placeholder="tcp://spectrum.example.com:1883"
                    class="w-full px-3 py-1.5 bg-gray-800 border border-gray-600 rounded text-sm"
                  />
                </div>
                <div class="grid grid-cols-2 gap-3">
                  <div>
                    <label class="block text-xs text-gray-400 mb-1">Scanner ID</label>
                    <input
                      v-model="mqttId"
                      type="text"
                      placeholder="UUID from server"
                      class="w-full px-3 py-1.5 bg-gray-800 border border-gray-600 rounded text-sm"
                    />
                  </div>
                  <div>
                    <label class="block text-xs text-gray-400 mb-1">Auth Token</label>
                    <input
                      v-model="mqttToken"
                      type="password"
                      placeholder="Token from server"
                      class="w-full px-3 py-1.5 bg-gray-800 border border-gray-600 rounded text-sm"
                    />
                  </div>
                </div>
                <button
                  @click="saveMQTTConfig"
                  class="w-full py-2 rounded text-sm font-medium transition-colors bg-gray-700 hover:bg-gray-600 text-white"
                >
                  Save Settings
                </button>
              </div>
            </div>

            <!-- Web Server Configuration -->
            <div class="bg-gray-900 rounded-lg p-4">
              <div class="flex items-center justify-between mb-4">
                <h4 class="text-sm font-medium text-gray-300">Local Web Server</h4>
                <div class="flex items-center gap-3">
                  <div class="flex items-center gap-2">
                    <!-- Spinner when pending -->
                    <svg v-if="store.serverStatus?.web === 'pending'" class="w-3 h-3 animate-spin text-cyan-400" viewBox="0 0 24 24" fill="none">
                      <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                      <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
                    </svg>
                    <span v-else
                      class="w-2 h-2 rounded-full"
                      :class="{
                        'bg-green-500': store.serverStatus?.web === 'connected',
                        'bg-red-500': store.serverStatus?.web === 'error',
                        'bg-gray-500': store.serverStatus?.web === 'disconnected'
                      }"
                    ></span>
                    <span class="text-xs text-gray-400">
                      {{ store.serverStatus?.web === 'pending' ? 'Starting...' :
                         store.serverStatus?.web === 'connected' ? 'Running' :
                         store.serverStatus?.web === 'error' ? 'Error' : 'Stopped' }}
                    </span>
                  </div>
                  <!-- Enable/Disable toggle switch -->
                  <button
                    @click="toggleWebServer"
                    :disabled="store.serverStatus?.web === 'pending'"
                    class="relative w-10 h-5 rounded-full transition-colors focus:outline-none focus:ring-2 focus:ring-cyan-500/50"
                    :class="store.serverStatus?.web === 'pending'
                      ? 'bg-gray-600 cursor-wait'
                      : store.webConfig?.enabled
                        ? 'bg-cyan-500'
                        : 'bg-gray-600'"
                  >
                    <span
                      class="absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform"
                      :class="store.webConfig?.enabled ? 'translate-x-5' : 'translate-x-0'"
                    ></span>
                  </button>
                </div>
              </div>

              <div class="space-y-3">
                <div>
                  <label class="block text-xs text-gray-400 mb-1">Port</label>
                  <input
                    v-model.number="webPort"
                    type="number"
                    min="1024"
                    max="65535"
                    class="w-full px-3 py-1.5 bg-gray-800 border border-gray-600 rounded text-sm"
                  />
                </div>
                <p class="text-xs text-gray-500">
                  Access via browser at
                  <span class="text-cyan-400">http://localhost:{{ webPort }}</span>
                </p>
                <button
                  @click="saveWebConfig"
                  class="w-full py-2 rounded text-sm font-medium transition-colors bg-gray-700 hover:bg-gray-600 text-white"
                >
                  Save Settings
                </button>
              </div>
            </div>
          </div>
        </div>
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
