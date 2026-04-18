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
      <div class="w-full px-2 py-2 sm:px-4 sm:py-4">
        <div class="flex items-center justify-between gap-2">
          <router-link to="/" class="flex items-center gap-2 sm:gap-3 min-w-0">
            <img src="/logo.png" alt="Micboard" class="h-7 sm:h-8" />
            <span class="text-base sm:text-xl font-bold text-white truncate">Spectrum Server</span>
          </router-link>
          <div class="flex items-center gap-2 sm:gap-4">
            <nav class="hidden sm:flex space-x-4">
              <router-link to="/" class="text-gray-300 hover:text-white">
                Dashboard
              </router-link>
            </nav>
            <div v-if="auth.isAuthenticated" class="flex items-center gap-2 sm:gap-3 sm:ml-4 sm:pl-4 sm:border-l border-gray-600">
              <!-- Read-only badge for share links -->
              <span v-if="auth.isReadonly" class="px-2 py-0.5 bg-purple-600 text-white text-xs rounded-full truncate max-w-[120px] sm:max-w-none">
                {{ auth.shareLabel || 'Demo' }} (View Only)
              </span>
              <span v-else class="text-gray-300 text-xs sm:text-sm hidden sm:inline">{{ auth.user?.username }}</span>
              <button
                @click="handleLogout"
                class="text-xs sm:text-sm text-gray-400 hover:text-white whitespace-nowrap"
              >
                Logout
              </button>
            </div>
          </div>
        </div>
      </div>
    </header>

    <main :class="route.path !== '/login' ? 'w-full px-2 py-3 sm:px-4 sm:py-6' : ''">
      <RouterView />
    </main>
  </div>
</template>
