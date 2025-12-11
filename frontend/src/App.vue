<script setup>
import { watch } from 'vue'
import { RouterView, useRoute, useRouter } from 'vue-router'
import { useScannersStore } from './stores/scanners'
import { useAuthStore } from './stores/auth'

const store = useScannersStore()
const auth = useAuthStore()
const route = useRoute()
const router = useRouter()

// Connect to MQTT when authenticated
watch(() => auth.isAuthenticated, (isAuth) => {
  if (isAuth) {
    store.connect()
    store.fetchScanners()
  } else {
    store.disconnect()
  }
}, { immediate: true })

async function handleLogout() {
  await auth.logout()
  router.push('/login')
}
</script>

<template>
  <div class="min-h-screen">
    <!-- Only show header on non-login pages -->
    <header v-if="route.path !== '/login'" class="bg-gray-800 border-b border-gray-700">
      <div class="max-w-7xl mx-auto px-4 py-4">
        <div class="flex items-center justify-between">
          <router-link to="/" class="text-xl font-bold text-white">
            Spectrum Server
          </router-link>
          <div class="flex items-center space-x-4">
            <nav class="flex space-x-4">
              <router-link to="/" class="text-gray-300 hover:text-white">
                Dashboard
              </router-link>
            </nav>
            <div v-if="auth.isAuthenticated" class="flex items-center space-x-3 ml-4 pl-4 border-l border-gray-600">
              <span class="text-gray-300 text-sm">{{ auth.user?.username }}</span>
              <button
                @click="handleLogout"
                class="text-sm text-gray-400 hover:text-white"
              >
                Logout
              </button>
            </div>
          </div>
        </div>
      </div>
    </header>

    <main :class="route.path !== '/login' ? 'max-w-7xl mx-auto px-4 py-6' : ''">
      <RouterView />
    </main>
  </div>
</template>
