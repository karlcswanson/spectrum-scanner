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
      // Enterprise SSO (python-social-auth) login/callback — forwarded to
      // Django. Keep the browser's original Host (changeOrigin: false): psa
      // builds the OAuth redirect_uri from the request Host, and it must match
      // this dev server's address (e.g. localhost:5174), not the internal
      // `server:8000`. No-op unless the backend enables SSO.
      '/oauth': {
        target: `http://${backendHost}:8000`,
        changeOrigin: false,
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
