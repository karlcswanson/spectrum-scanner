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

const routes = [
  { path: '/', component: Dashboard, meta: { requiresAuth: true } },
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

app.mount('#app')
