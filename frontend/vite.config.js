import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'

// Use Docker service names when running in container, localhost for local dev
const backendHost = process.env.DOCKER_ENV ? 'server' : 'localhost'
const mqttHost = process.env.DOCKER_ENV ? 'mosquitto' : 'localhost'

// Build mode: 'main' (central server) or 'standalone' (Go scanner)
const buildMode = process.env.BUILD_MODE || 'main'

// Base config shared by both builds
const baseConfig = {
  plugins: [vue()],
  resolve: {
    alias: {
      '@lib': resolve(__dirname, 'src/lib'),
      '@components': resolve(__dirname, 'src/components'),
    },
  },
}

// Main app config (central server with auth, multi-scanner)
const mainConfig = {
  ...baseConfig,
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
      '/mqtt': {
        target: `ws://${mqttHost}:9001`,
        ws: true,
      },
    },
  },
}

// Standalone config (single scanner, no auth, Go API)
const standaloneConfig = {
  ...baseConfig,
  root: '.',
  build: {
    outDir: 'dist-standalone',
    emptyOutDir: true,
    rollupOptions: {
      input: {
        index: resolve(__dirname, 'standalone.html'),
      },
      output: {
        // Rename standalone.html to index.html in output
        entryFileNames: 'assets/[name]-[hash].js',
      },
    },
  },
  server: {
    port: 5174,
    proxy: {
      '/api': {
        target: 'http://localhost:8080',
        changeOrigin: true,
      },
      '/ws': {
        target: 'ws://localhost:8080',
        ws: true,
      },
    },
  },
}

export default defineConfig(buildMode === 'standalone' ? standaloneConfig : mainConfig)
