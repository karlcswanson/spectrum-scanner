import { createApp } from 'vue'
import { createPinia } from 'pinia'
import { createRouter, createWebHistory } from 'vue-router'

import App from './App.vue'
import './style.css'

// Views
import Dashboard from './views/Dashboard.vue'
import ScannerDetail from './views/ScannerDetail.vue'

const routes = [
  { path: '/', component: Dashboard },
  { path: '/scanner/:id', component: ScannerDetail },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

const pinia = createPinia()
const app = createApp(App)

app.use(pinia)
app.use(router)
app.mount('#app')
