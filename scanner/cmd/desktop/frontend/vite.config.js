import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      // Share components and lib from main frontend
      '@components': resolve(__dirname, '../../../../frontend/src/components'),
      '@lib': resolve(__dirname, '../../../../frontend/src/lib'),
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
})
