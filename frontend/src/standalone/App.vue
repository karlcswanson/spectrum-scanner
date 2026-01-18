<script setup>
import { onMounted, onUnmounted, ref, computed, watch } from 'vue'
import { useStandaloneStore, scanBus } from './store'
import D3SpectrumChart from '../components/D3SpectrumChart.vue'

const store = useStandaloneStore()

// UI state
const showSettings = ref(false)
const gainValue = ref(40)
const gainMode = ref('manual')

// Trace display modes
const showCurrent = ref(true)
const showAverage = ref(false)
const showPeak = ref(false)

// Track chart refs for peak reset
const chartRefs = ref({})

// Sync gain from config
watch(() => store.settings, (settings) => {
  gainValue.value = settings.rx_gain
  gainMode.value = settings.rx_gain_mode.toLowerCase()
}, { immediate: true })

// Connect on mount
onMounted(() => {
  store.connect()
})

onUnmounted(() => {
  store.disconnect()
})

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
function exportCSV(bandName) {
  const scan = store.getScanData(bandName)
  if (!scan) return

  let csv = 'Frequency (MHz),Power (dBm)\n'
  const startMHz = scan.hz_lo / 1e6
  const stepMHz = scan.step / 1e6

  for (let i = 0; i < scan.power.length; i++) {
    const freq = startMHz + (i * stepMHz)
    csv += `${freq.toFixed(6)},${scan.power[i].toFixed(2)}\n`
  }

  const blob = new Blob([csv], { type: 'text/csv' })
  const url = URL.createObjectURL(blob)
  const timestamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19)
  const filename = `scan_${bandName.replace(/\s+/g, '-')}_${timestamp}.csv`

  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
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
</script>

<template>
  <div class="min-h-screen bg-gray-900 text-white">
    <!-- Header -->
    <header class="bg-gray-800 border-b border-gray-700 px-6 py-4">
      <div class="flex items-center justify-between">
        <div class="flex items-center gap-4">
          <h1 class="text-xl font-bold text-cyan-400">Spectrum Scanner</h1>
          <span v-if="store.config?.name" class="text-gray-400">
            {{ store.config.name }}
          </span>
        </div>

        <div class="flex items-center gap-4">
          <!-- Error indicator -->
          <div
            v-if="store.lastError && Date.now() - store.lastError.timestamp < 10000"
            class="flex items-center gap-2 text-red-400 text-sm"
          >
            <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
            </svg>
            <span>{{ store.lastError.message }}</span>
          </div>

          <!-- Connection status -->
          <div class="flex items-center gap-2">
            <span
              class="w-3 h-3 rounded-full"
              :class="store.connected ? 'bg-green-500' : 'bg-red-500'"
            ></span>
            <span class="text-sm text-gray-400">
              {{ store.connected ? 'Connected' : 'Disconnected' }}
            </span>
          </div>

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

          <!-- Settings toggle -->
          <button
            @click="showSettings = !showSettings"
            class="p-2 rounded hover:bg-gray-700"
            :class="showSettings ? 'text-cyan-400' : 'text-gray-400'"
          >
            <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
            </svg>
          </button>
        </div>
      </div>

      <!-- Settings panel -->
      <div v-if="showSettings" class="mt-4 pt-4 border-t border-gray-700">
        <div class="grid md:grid-cols-2 gap-6">
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
    </main>
  </div>
</template>
