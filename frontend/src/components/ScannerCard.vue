<script setup>
import { computed } from 'vue'

const props = defineProps({
  scanner: {
    type: Object,
    required: true,
  },
})

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
</script>

<template>
  <router-link
    :to="`/scanner/${scanner.id}`"
    class="block bg-gray-800 rounded-lg p-4 hover:bg-gray-750 transition-colors border border-gray-700 hover:border-gray-600"
  >
    <div class="flex items-start justify-between">
      <div>
        <h3 class="font-semibold text-lg">{{ scanner.name }}</h3>
        <p class="text-sm text-gray-400">{{ scanner.location || 'No location' }}</p>
      </div>
      <div class="flex items-center space-x-2">
        <span class="w-2 h-2 rounded-full" :class="statusColor"></span>
        <span class="text-sm text-gray-400">{{ statusText }}</span>
      </div>
    </div>

    <div class="mt-3 text-sm text-gray-500">
      <span class="inline-block bg-gray-700 rounded px-2 py-0.5">
        {{ scanner.scanner_type || scanner.type }}
      </span>
      <span v-if="scanner.current_band" class="ml-2">
        {{ scanner.current_band }}
      </span>
    </div>
  </router-link>
</template>
