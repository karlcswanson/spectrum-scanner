<script setup>
import { computed } from 'vue'
import { useScannersStore } from '../stores/scanners'
import SpectrumChart from './SpectrumChart.vue'

const props = defineProps({
  scannerId: {
    type: String,
    required: true,
  },
  scannerName: {
    type: String,
    default: '',
  },
  band: {
    type: Object,
    required: true,
  },
  scan: {
    type: Object,
    default: null,
  },
  height: {
    type: Number,
    default: 300,
  },
  showScanner: {
    type: Boolean,
    default: true,
  },
})

const store = useScannersStore()

const scanInfo = computed(() => {
  if (!props.scan?.power) return '--'
  const points = props.scan.power.length
  const minP = Math.min(...props.scan.power).toFixed(1)
  const maxP = Math.max(...props.scan.power).toFixed(1)
  return `${points} pts | ${minP} to ${maxP} dBm`
})

const freqRange = computed(() => {
  const start = (props.band.start_hz / 1e6).toFixed(0)
  const stop = (props.band.stop_hz / 1e6).toFixed(0)
  return `${start}-${stop} MHz`
})

function exportCSV() {
  store.exportScanCSV(props.scannerId, props.band.name)
}
</script>

<template>
  <div class="bg-gray-800 rounded-lg p-4">
    <div class="flex justify-between items-center mb-3">
      <div>
        <h2 class="text-lg font-semibold text-cyan-400">
          {{ band.name }}
          <span class="text-gray-500 font-normal text-sm ml-2">
            ({{ freqRange }})
          </span>
        </h2>
        <p class="text-xs text-gray-500">
          <span v-if="showScanner && scannerName" class="mr-3">{{ scannerName }}</span>
          {{ scanInfo }}
        </p>
      </div>
      <button
        @click="exportCSV"
        :disabled="!scan"
        class="px-4 py-2 rounded text-sm font-semibold transition-colors"
        :class="scan
          ? 'bg-green-500 hover:bg-green-600 text-black'
          : 'bg-gray-600 text-gray-400 cursor-not-allowed'"
      >
        Export CSV
      </button>
    </div>
    <SpectrumChart
      :scan="scan || {}"
      :band="band"
      :height="height"
    />
  </div>
</template>
