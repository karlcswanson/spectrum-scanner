<script setup>
import { ref } from 'vue'
import D3SpectrumChart from './D3SpectrumChart.vue'
import { formatFreqRange } from '@lib'

const props = defineProps({
  band: { type: Object, required: true },
  scanBus: { type: Object, required: true },
  getScanData: { type: Function, required: true },
  getScanInfo: { type: Function, required: true },
  scanUpdateCount: { type: Number, default: 0 },
  onExport: { type: Function, default: null },
})

// Trace display modes
const showCurrent = ref(true)
const showAverage = ref(false)
const showPeak = ref(false)

// Chart ref for peak reset
const chartRef = ref(null)

// Format frequency range for display
function formatBandRange() {
  return formatFreqRange(props.band.start_hz, props.band.stop_hz)
}

// Get band object for chart
function getBandForChart() {
  return {
    name: props.band.name,
    start_hz: props.band.start_hz,
    stop_hz: props.band.stop_hz,
  }
}

function resetPeakHold() {
  if (chartRef.value) {
    chartRef.value.resetAllPeaks()
  }
}

function handleExport() {
  if (props.onExport) {
    props.onExport(props.band.name)
  }
}

const hasScanData = () => !!props.getScanData(props.band.name)
</script>

<template>
  <div class="bg-gray-800 rounded-lg p-4">
    <div class="flex justify-between items-start mb-3">
      <div>
        <h2 class="text-lg font-semibold text-cyan-400">
          {{ band.name }}
          <span class="text-gray-500 font-normal text-sm ml-2">
            ({{ formatBandRange() }})
          </span>
        </h2>
        <p class="text-xs text-gray-500" :data-v="scanUpdateCount">
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
            @click="resetPeakHold"
            class="px-2 py-0.5 rounded text-xs bg-gray-700 hover:bg-gray-600 text-gray-300"
          >
            Reset
          </button>
        </div>

        <button
          v-if="onExport"
          @click="handleExport"
          :disabled="!hasScanData()"
          class="px-4 py-2 rounded text-sm font-semibold transition-colors"
          :class="hasScanData()
            ? 'bg-green-500 hover:bg-green-600 text-black'
            : 'bg-gray-600 text-gray-400 cursor-not-allowed'"
        >
          Export CSV
        </button>
      </div>
    </div>

    <D3SpectrumChart
      ref="chartRef"
      :band-name="band.name"
      :scan-bus="scanBus"
      :get-scan-data="getScanData"
      :band="getBandForChart()"
      :height="300"
      :show-current="showCurrent"
      :show-average="showAverage"
      :show-peak="showPeak"
    />
  </div>
</template>
