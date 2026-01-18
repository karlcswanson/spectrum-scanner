<script setup>
import { ref, watch } from 'vue'

const props = defineProps({
  config: { type: Object, default: null },
  bands: { type: Array, default: () => [] },
  settings: { type: Object, default: () => ({ rx_gain: 40, rx_gain_mode: 'manual' }) },
})

const emit = defineEmits(['update:name', 'update:gain', 'toggle-band'])

// Local form state
const scannerName = ref('')
const gainValue = ref(40)
const gainMode = ref('manual')

// Sync scanner name from config
watch(() => props.config, (config) => {
  if (config) {
    scannerName.value = config.name || ''
  }
}, { immediate: true })

// Sync gain from settings
watch(() => props.settings, (settings) => {
  gainValue.value = settings.rx_gain
  gainMode.value = settings.rx_gain_mode.toLowerCase()
}, { immediate: true })

function applyName() {
  emit('update:name', scannerName.value)
}

function applyGain() {
  emit('update:gain', gainValue.value, gainMode.value)
}

function handleToggleBand(bandName) {
  emit('toggle-band', bandName)
}
</script>

<template>
  <div class="grid md:grid-cols-3 gap-6">
    <!-- Scanner Name -->
    <div>
      <h4 class="text-sm font-medium text-gray-300 mb-3">Scanner Name</h4>
      <div class="flex items-center gap-2">
        <input
          v-model="scannerName"
          type="text"
          placeholder="e.g. Studio A"
          class="flex-1 px-3 py-1.5 bg-gray-900 border border-gray-600 rounded text-sm"
        />
        <button
          @click="applyName"
          class="px-3 py-1.5 bg-cyan-500 hover:bg-cyan-600 text-black text-sm font-medium rounded"
        >
          Apply
        </button>
      </div>
      <p class="text-xs text-gray-500 mt-1">Identifies this scanner instance</p>
    </div>

    <!-- Bands -->
    <div>
      <h4 class="text-sm font-medium text-gray-300 mb-3">Bands</h4>
      <div class="flex flex-wrap gap-2">
        <label
          v-for="band in bands"
          :key="band.name"
          class="flex items-center gap-2 px-3 py-1.5 rounded cursor-pointer text-sm transition-colors"
          :class="band.enabled
            ? 'bg-cyan-900/50 border border-cyan-500 text-cyan-300'
            : 'bg-gray-700 hover:bg-gray-600 text-gray-300 border border-transparent'"
        >
          <input
            type="checkbox"
            :checked="band.enabled"
            @change="handleToggleBand(band.name)"
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
</template>
