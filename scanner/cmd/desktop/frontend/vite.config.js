import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      // Share components from main frontend
      '@components': resolve(__dirname, '../../../../frontend/src/components'),
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
})
