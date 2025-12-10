<script setup>
import { onMounted } from 'vue'
import { RouterView } from 'vue-router'
import { useScannersStore } from './stores/scanners'

const store = useScannersStore()

onMounted(() => {
  // Establish single WebSocket connection at app level
  store.connect()
  store.fetchScanners()
})
</script>

<template>
  <div class="min-h-screen">
    <header class="bg-gray-800 border-b border-gray-700">
      <div class="max-w-7xl mx-auto px-4 py-4">
        <div class="flex items-center justify-between">
          <router-link to="/" class="text-xl font-bold text-white">
            Spectrum Server
          </router-link>
          <nav class="flex space-x-4">
            <router-link to="/" class="text-gray-300 hover:text-white">
              Dashboard
            </router-link>
          </nav>
        </div>
      </div>
    </header>

    <main class="max-w-7xl mx-auto px-4 py-6">
      <RouterView />
    </main>
  </div>
</template>
