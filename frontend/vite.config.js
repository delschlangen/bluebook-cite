import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  base: '/bluebook-cite/',
  build: {
    outDir: 'dist',
  },
  test: {
    // Some tests render a few hundred cards and press keys on them; allow for a slow or busy machine.
    testTimeout: 15000,
  },
  server: {
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
