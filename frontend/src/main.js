import { createApp } from 'vue'
import { createPinia } from 'pinia'
import { createRouter, createWebHistory } from 'vue-router'

import App from './App.vue'
import './style.css'

// Views
import Dashboard from './views/Dashboard.vue'
import ScannerDetail from './views/ScannerDetail.vue'
import Login from './views/Login.vue'

// Stores
import { useAuthStore } from './stores/auth'
import { loadConfig } from './lib/brand'

const routes = [
  { path: '/', component: Dashboard, meta: { requiresAuth: true } },
  { path: '/scanner/:id/band/:bandName', component: ScannerDetail, meta: { requiresAuth: true } },
  { path: '/scanner/:id', component: ScannerDetail, meta: { requiresAuth: true } },
  { path: '/login', component: Login, meta: { guest: true } },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

const pinia = createPinia()
const app = createApp(App)

app.use(pinia)
app.use(router)

// Navigation guard for auth
router.beforeEach(async (to, from, next) => {
  const auth = useAuthStore()

  // Always check auth on initial load (loading=true means we haven't checked yet)
  if (auth.loading) {
    await auth.checkAuth()
  }

  if (to.meta.requiresAuth && !auth.isAuthenticated) {
    next('/login')
  } else if (to.meta.guest && auth.isAuthenticated) {
    next('/')
  } else {
    next()
  }
})

// Load branding before first paint so the login/header never flash the default
// identity, then mount. loadConfig never rejects and is bounded by its own
// timeout, so a slow/dead server can't hang us — .finally mounts regardless.
loadConfig().finally(() => app.mount('#app'))
