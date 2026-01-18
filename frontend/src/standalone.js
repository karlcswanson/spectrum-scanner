import { createApp } from 'vue'
import { createPinia } from 'pinia'

import StandaloneApp from './standalone/App.vue'
import './style.css'

const pinia = createPinia()
const app = createApp(StandaloneApp)

app.use(pinia)
app.mount('#app')
