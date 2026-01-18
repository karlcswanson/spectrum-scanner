<script setup>
import { onMounted, onUnmounted, ref, computed, watch } from 'vue'
import { useDesktopStore, scanBus } from './store'
import D3SpectrumChart from '@components/D3SpectrumChart.vue'

const store = useDesktopStore()

// Reactive error display (updates every second instead of every render)
const now = ref(Date.now())
let nowInterval = null

onUnmounted(() => {
  if (nowInterval) clearInterval(nowInterval)
})

const showError = computed(() => {
  return store.lastError && (now.value - store.lastError.timestamp) < 10000
})

// Connection state
const plutoAddress = ref('https://192.168.2.1')
const connecting = ref(false)
const showSettings = ref(false)
const settingsTab = ref('scanner') // 'scanner' or 'server'

// Gain controls
const gainValue = ref(40)
const gainMode = ref('manual')

// Trace display modes
const showCurrent = ref(true)
const showAverage = ref(false)
const showPeak = ref(false)

// Chart refs for peak reset
const chartRefs = ref({})

// Server mode form fields
const mqttBroker = ref('')
const mqttId = ref('')
const mqttToken = ref('')
const mqttName = ref('')
const mqttLocation = ref('')
const webPort = ref(8080)

// Sync gain from config
watch(() => store.settings, (settings) => {
  gainValue.value = settings.rx_gain
  gainMode.value = settings.rx_gain_mode.toLowerCase()
}, { immediate: true })

// Sync MQTT config from store
watch(() => store.mqttConfig, (cfg) => {
  mqttBroker.value = cfg.broker || ''
  mqttId.value = cfg.id || ''
  mqttToken.value = cfg.token || ''
  mqttName.value = cfg.name || ''
  mqttLocation.value = cfg.location || ''
}, { immediate: true })

// Sync web config from store
watch(() => store.webConfig, (cfg) => {
  webPort.value = cfg.port || 8080
}, { immediate: true })

// Initialize on mount
onMounted(async () => {
  // Start error display timer
  nowInterval = setInterval(() => {
    now.value = Date.now()
  }, 1000)

  store.init()

  // Try to auto-detect Pluto
  const detected = await store.detectPluto()
  if (detected) {
    plutoAddress.value = detected
  }
})

async function handleConnect() {
  connecting.value = true
  await store.connect(plutoAddress.value)
  connecting.value = false
}

async function handleDisconnect() {
  await store.disconnect()
}

// Getter function for scan data (passed to chart component)
function getScanData(bandName) {
  return store.getScanData(bandName)
}

// Get band object for chart
function getBandForChart(band) {
  return {
    name: band.name,
    start_hz: band.start_hz,
    stop_hz: band.stop_hz,
  }
}

// Format frequency range
function formatFreqRange(band) {
  const start = (band.start_hz / 1e6).toFixed(0)
  const stop = (band.stop_hz / 1e6).toFixed(0)
  return `${start}-${stop} MHz`
}

// Scan info for a band
function getScanInfo(bandName) {
  const scan = store.getScanData(bandName)
  if (!scan?.power) return '--'
  const points = scan.power.length
  const minP = Math.min(...scan.power).toFixed(1)
  const maxP = Math.max(...scan.power).toFixed(1)
  return `${points} pts | ${minP} to ${maxP} dBm`
}

// Export CSV for a band
async function exportCSV(bandName) {
  const scan = store.getScanData(bandName)
  if (!scan) return

  let csv = 'Frequency (MHz),Power (dBm)\n'
  const startMHz = scan.hz_lo / 1e6
  const stepMHz = scan.step / 1e6

  for (let i = 0; i < scan.power.length; i++) {
    const freq = startMHz + (i * stepMHz)
    csv += `${freq.toFixed(6)},${scan.power[i].toFixed(2)}\n`
  }

  const timestamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19)
  const filename = `scan_${bandName.replace(/\s+/g, '-')}_${timestamp}.csv`

  // Use Wails backend to save file with native dialog
  const wails = window.go?.main?.App
  if (wails?.SaveCSV) {
    try {
      const savedPath = await wails.SaveCSV(csv, filename)
      if (savedPath) {
        console.log('Saved CSV to:', savedPath)
      }
    } catch (err) {
      console.error('Failed to save CSV:', err)
    }
  }
}

function resetPeakHold(bandName) {
  const chart = chartRefs.value[bandName]
  if (chart) {
    chart.resetAllPeaks()
  }
}

function applyGain() {
  store.updateGain(gainValue.value, gainMode.value)
}

// Server mode functions
async function saveMQTTConfig() {
  await store.setMQTTConfig({
    enabled: store.mqttConfig.enabled,
    broker: mqttBroker.value,
    id: mqttId.value,
    token: mqttToken.value,
    name: mqttName.value,
    location: mqttLocation.value,
  })
}

async function saveWebConfig() {
  await store.setWebConfig({
    enabled: store.webConfig.enabled,
    port: webPort.value,
  })
}

async function toggleMQTT() {
  // Save config first
  await saveMQTTConfig()

  if (store.serverStatus.mqtt_connected) {
    await store.disableMQTT()
  } else {
    await store.enableMQTT()
  }

  // Persist to YAML so it auto-starts on next launch
  await store.saveConfig()
}

async function toggleWebServer() {
  // Save config first
  await saveWebConfig()

  if (store.serverStatus.web_running) {
    await store.disableWebServer()
  } else {
    await store.enableWebServer()
  }

  // Persist to YAML so it auto-starts on next launch
  await store.saveConfig()
}

async function saveAllConfig() {
  await saveMQTTConfig()
  await saveWebConfig()
  await store.saveConfig()
}
</script>

<template>
  <div class="min-h-screen bg-gray-900 text-white">
    <!-- Header -->
    <header class="bg-gray-800 border-b border-gray-700 px-6 py-4">
      <div class="flex items-center justify-between">
        <div class="flex items-center gap-4">
          <img src="/logo.png" alt="Micboard" class="h-8 w-8" />
          <h1 class="text-xl font-bold text-cyan-400">Spectrum Scanner</h1>
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

          <!-- Server status - clickable to open server settings -->
          <button @click="showSettings = true; settingsTab = 'server'"
               class="flex items-center gap-2 px-3 py-1.5 rounded bg-gray-700 hover:bg-gray-600 transition-colors"
          >
            <span
              class="w-2 h-2 rounded-full"
              :class="store.serverStatus.mqtt_connected ? 'bg-green-500' : 'bg-gray-500'"
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

          <!-- Connect/Disconnect -->
          <template v-if="store.connected">
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

            <button
              @click="handleDisconnect"
              class="px-4 py-2 bg-gray-600 hover:bg-gray-500 text-white rounded"
            >
              Disconnect
            </button>
          </template>
        </div>
      </div>

      <!-- Settings panel -->
      <div v-if="showSettings" class="mt-4 pt-4 border-t border-gray-700">
        <!-- Close button -->
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
        <div v-if="settingsTab === 'scanner'" class="grid md:grid-cols-2 gap-6">
          <!-- Bands -->
          <div>
            <h4 class="text-sm font-medium text-gray-300 mb-3">Bands</h4>
            <div class="flex flex-wrap gap-2">
              <label
                v-for="band in store.bands"
                :key="band.name"
                class="flex items-center gap-2 px-3 py-1.5 rounded cursor-pointer text-sm transition-colors"
                :class="band.enabled
                  ? 'bg-cyan-900/50 border border-cyan-500 text-cyan-300'
                  : 'bg-gray-700 hover:bg-gray-600 text-gray-300 border border-transparent'"
              >
                <input
                  type="checkbox"
                  :checked="band.enabled"
                  @change="store.toggleBand(band.name)"
                  class="w-3.5 h-3.5 accent-cyan-400"
                />
                <span>{{ band.name }}</span>
              </label>
            </div>
          </div>

          <!-- Gain -->
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

        <!-- Server mode settings -->
        <div v-if="settingsTab === 'server'" class="space-y-6">
          <div class="grid md:grid-cols-2 gap-6">
            <!-- MQTT Configuration -->
            <div class="bg-gray-900 rounded-lg p-4">
              <div class="flex items-center justify-between mb-4">
                <h4 class="text-sm font-medium text-gray-300">MQTT (Spectrum Server)</h4>
                <div class="flex items-center gap-2">
                  <span
                    class="w-2 h-2 rounded-full"
                    :class="store.serverStatus.mqtt_connected ? 'bg-green-500' : 'bg-gray-500'"
                  ></span>
                  <span class="text-xs text-gray-400">
                    {{ store.serverStatus.mqtt_connected ? 'Connected' : 'Disconnected' }}
                  </span>
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
                <div class="grid grid-cols-2 gap-3">
                  <div>
                    <label class="block text-xs text-gray-400 mb-1">Display Name</label>
                    <input
                      v-model="mqttName"
                      type="text"
                      placeholder="My Scanner"
                      class="w-full px-3 py-1.5 bg-gray-800 border border-gray-600 rounded text-sm"
                    />
                  </div>
                  <div>
                    <label class="block text-xs text-gray-400 mb-1">Location</label>
                    <input
                      v-model="mqttLocation"
                      type="text"
                      placeholder="Studio A"
                      class="w-full px-3 py-1.5 bg-gray-800 border border-gray-600 rounded text-sm"
                    />
                  </div>
                </div>
                <button
                  @click="toggleMQTT"
                  class="w-full py-2 rounded text-sm font-medium transition-colors"
                  :class="store.serverStatus.mqtt_connected
                    ? 'bg-red-500 hover:bg-red-600 text-white'
                    : 'bg-cyan-500 hover:bg-cyan-600 text-black'"
                >
                  {{ store.serverStatus.mqtt_connected ? 'Disconnect' : 'Connect' }}
                </button>
              </div>
            </div>

            <!-- Web Server Configuration -->
            <div class="bg-gray-900 rounded-lg p-4">
              <div class="flex items-center justify-between mb-4">
                <h4 class="text-sm font-medium text-gray-300">Local Web Server</h4>
                <div class="flex items-center gap-2">
                  <span
                    class="w-2 h-2 rounded-full"
                    :class="store.serverStatus.web_running ? 'bg-green-500' : 'bg-gray-500'"
                  ></span>
                  <span class="text-xs text-gray-400">
                    {{ store.serverStatus.web_running ? 'Running' : 'Stopped' }}
                  </span>
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
                  @click="toggleWebServer"
                  class="w-full py-2 rounded text-sm font-medium transition-colors"
                  :class="store.serverStatus.web_running
                    ? 'bg-red-500 hover:bg-red-600 text-white'
                    : 'bg-cyan-500 hover:bg-cyan-600 text-black'"
                >
                  {{ store.serverStatus.web_running ? 'Stop Server' : 'Start Server' }}
                </button>
              </div>
            </div>
          </div>

          <!-- Save config button -->
          <div class="flex items-center justify-between pt-4 border-t border-gray-700">
            <p class="text-xs text-gray-500">
              Config: {{ store.configPath }}
            </p>
            <button
              @click="saveAllConfig"
              class="px-4 py-2 bg-green-500 hover:bg-green-600 text-black text-sm font-medium rounded"
            >
              Save Configuration
            </button>
          </div>
        </div>
      </div>
    </header>

    <!-- Main content -->
    <main class="p-6">
      <!-- Connection screen (when not connected) -->
      <div v-if="!store.connected" class="max-w-md mx-auto mt-20">
        <div class="bg-gray-800 rounded-lg p-8">
          <h2 class="text-xl font-semibold text-center mb-6">Connect to ADALM-Pluto</h2>

          <div class="space-y-4">
            <div>
              <label class="block text-sm text-gray-400 mb-2">Device Address</label>
              <input
                v-model="plutoAddress"
                type="text"
                placeholder="https://192.168.2.1"
                class="w-full px-4 py-2 bg-gray-900 border border-gray-600 rounded text-white"
                :disabled="connecting"
              />
              <p class="text-xs text-gray-500 mt-1">
                Default USB: 192.168.2.1
              </p>
            </div>

            <button
              @click="handleConnect"
              :disabled="connecting"
              class="w-full py-3 bg-cyan-500 hover:bg-cyan-600 disabled:bg-gray-600 text-black font-semibold rounded"
            >
              {{ connecting ? 'Connecting...' : 'Connect' }}
            </button>
          </div>
        </div>
      </div>

      <!-- Scanner view (when connected) -->
      <template v-else>
        <!-- No bands message -->
        <div
          v-if="store.enabledBands.length === 0"
          class="text-center text-gray-500 py-12"
        >
          No bands enabled. Configure bands in settings.
        </div>

        <!-- Band charts -->
        <div class="space-y-6">
          <div
            v-for="band in store.enabledBands"
            :key="band.name"
            class="bg-gray-800 rounded-lg p-4"
          >
            <div class="flex justify-between items-start mb-3">
              <div>
                <h2 class="text-lg font-semibold text-cyan-400">
                  {{ band.name }}
                  <span class="text-gray-500 font-normal text-sm ml-2">
                    ({{ formatFreqRange(band) }})
                  </span>
                </h2>
                <p class="text-xs text-gray-500" :data-v="store.scanUpdateCount">
                  {{ getScanInfo(band.name) }}
                </p>
              </div>

              <div class="flex items-center gap-3">
                <!-- Trace toggles -->
                <div class="flex items-center gap-2 text-xs">
                  <label class="flex items-center gap-1 cursor-pointer">
                    <input type="checkbox" v-model="showCurrent" class="w-3 h-3 accent-cyan-400" />
                    <span class="text-gray-400">Current</span>
                  </label>
                  <label class="flex items-center gap-1 cursor-pointer">
                    <input type="checkbox" v-model="showAverage" class="w-3 h-3 accent-yellow-400" />
                    <span class="text-gray-400">Avg</span>
                  </label>
                  <label class="flex items-center gap-1 cursor-pointer">
                    <input type="checkbox" v-model="showPeak" class="w-3 h-3 accent-red-400" />
                    <span class="text-gray-400">Peak</span>
                  </label>
                  <button
                    v-if="showPeak"
                    @click="resetPeakHold(band.name)"
                    class="px-2 py-0.5 rounded text-xs bg-gray-700 hover:bg-gray-600 text-gray-300"
                  >
                    Reset
                  </button>
                </div>

                <button
                  @click="exportCSV(band.name)"
                  :disabled="!store.getScanData(band.name)"
                  class="px-4 py-2 rounded text-sm font-semibold transition-colors"
                  :class="store.getScanData(band.name)
                    ? 'bg-green-500 hover:bg-green-600 text-black'
                    : 'bg-gray-600 text-gray-400 cursor-not-allowed'"
                >
                  Export CSV
                </button>
              </div>
            </div>

            <D3SpectrumChart
              :ref="el => { if (el) chartRefs[band.name] = el }"
              :band-name="band.name"
              :scan-bus="scanBus"
              :get-scan-data="getScanData"
              :band="getBandForChart(band)"
              :height="300"
              :show-current="showCurrent"
              :show-average="showAverage"
              :show-peak="showPeak"
            />
          </div>
        </div>
      </template>
    </main>
  </div>
</template>
