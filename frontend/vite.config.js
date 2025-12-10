import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// Use Docker service name when running in container, localhost for local dev
const backendHost = process.env.DOCKER_ENV ? 'server' : 'localhost'

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: `http://${backendHost}:8000`,
        changeOrigin: true,
      },
      '/ws': {
        target: `ws://${backendHost}:8000`,
        ws: true,
      },
    },
  },
})
