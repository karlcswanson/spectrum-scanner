<script setup>
import { computed, ref, watch, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useScannersStore } from '../stores/scanners'
import ScannerBandGrid from '../components/ScannerBandGrid.vue'

const store = useScannersStore()
const route = useRoute()
const router = useRouter()

// Active group filter (null = all scanners)
const activeGroupId = ref(null)

// Sync filter with URL query param
onMounted(() => {
  store.fetchGroups()
  if (route.query.group) {
    activeGroupId.value = route.query.group
  }
})

watch(() => route.query.group, (groupId) => {
  activeGroupId.value = groupId || null
})

function setGroup(groupId) {
  if (groupId === activeGroupId.value) return
  activeGroupId.value = groupId
  if (groupId) {
    router.replace({ query: { group: groupId } })
  } else {
    router.replace({ query: {} })
  }
}

// Active group object (for showing description etc.)
const activeGroup = computed(() => {
  if (!activeGroupId.value) return null
  return store.groups.find(g => g.id === activeGroupId.value) || null
})

// Filter scanners by active group
const filteredScanners = computed(() => {
  if (!activeGroupId.value) return store.scannerList

  // Find scanners that belong to the selected group
  const group = activeGroup.value
  if (!group) return store.scannerList

  // Use the group's scanner list if we have it cached, otherwise filter by scanner_groups
  // Since scanners come from MQTT/store and groups from API, we need to cross-reference
  // Scanners in the store may have scanner_groups populated from the API fetch
  return store.scannerList.filter(s => {
    // Check if this scanner's groups include the active group
    const scannerGroups = s.scanner_groups || s.deployments || []
    return scannerGroups.some(g => {
      const gId = typeof g === 'object' ? g.id : g
      return gId === activeGroupId.value
    })
  })
})

// Online scanners (from filtered set) for quick links
const onlineScanners = computed(() =>
  filteredScanners.value.filter(s => s.online)
)

function scrollToScanner(scannerId) {
  const el = document.getElementById(`scanner-${scannerId}`)
  if (el) {
    el.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }
}
</script>

<template>
  <div>
    <!-- Header with connection status -->
    <div class="flex flex-wrap items-center justify-between gap-2 mb-4">
      <h1 class="text-xl sm:text-2xl font-bold">Dashboard</h1>
      <div class="flex items-center gap-4">
        <!-- Error indicator -->
        <div
          v-if="store.lastError && Date.now() - store.lastError.timestamp < 10000"
          class="flex items-center space-x-2 text-red-400 text-sm"
        >
          <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
          </svg>
          <span>{{ store.lastError.message }}</span>
        </div>

        <!-- Connection status -->
        <div class="flex items-center space-x-2">
          <span
            class="w-3 h-3 rounded-full"
            :class="store.connected ? 'bg-green-500' : 'bg-red-500'"
          ></span>
          <span class="text-sm text-gray-400">
            {{ store.connected ? 'Connected' : 'Disconnected' }}
          </span>
        </div>
      </div>
    </div>

    <!-- Group filter pills -->
    <div v-if="store.groups.length > 0" class="flex flex-wrap items-center gap-2 mb-4">
      <button
        @click="setGroup(null)"
        class="px-3 py-1.5 text-sm rounded-full transition-colors"
        :class="!activeGroupId
          ? 'bg-cyan-600 text-white'
          : 'bg-gray-700 text-gray-300 hover:bg-gray-600 hover:text-white'"
      >
        All
      </button>
      <button
        v-for="group in store.groups"
        :key="group.id"
        @click="setGroup(group.id)"
        class="px-3 py-1.5 text-sm rounded-full transition-colors"
        :class="activeGroupId === group.id
          ? 'bg-cyan-600 text-white'
          : 'bg-gray-700 text-gray-300 hover:bg-gray-600 hover:text-white'"
      >
        {{ group.name }}
        <span class="ml-1 text-xs opacity-60">{{ group.scanner_count }}</span>
      </button>
    </div>

    <!-- Online scanners quick links -->
    <div v-if="onlineScanners.length" class="flex flex-wrap items-center gap-2 mb-6">
      <span class="text-gray-500 text-sm">Online:</span>
      <button
        v-for="scanner in onlineScanners"
        :key="scanner.id"
        @click="scrollToScanner(scanner.id)"
        class="px-2 py-1 text-sm rounded bg-green-600/20 text-green-400 hover:bg-green-600/30 hover:text-green-300 cursor-pointer"
      >
        {{ scanner.name === scanner.id ? scanner.id.slice(0, 8) : (scanner.name || scanner.id.slice(0, 8)) }}
      </button>
    </div>

    <!-- No scanners message -->
    <div
      v-if="store.scannerList.length === 0"
      class="text-center text-gray-500 py-12"
    >
      No scanners connected. Waiting for data...
    </div>

    <!-- Filtered empty state -->
    <div
      v-else-if="activeGroupId && filteredScanners.length === 0"
      class="text-center text-gray-500 py-12"
    >
      No scanners in this group.
    </div>

    <!-- Scanner band grid with comparison -->
    <ScannerBandGrid :scanners="filteredScanners" />
  </div>
</template>
