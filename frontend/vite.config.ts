import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { fileURLToPath, URL } from 'node:url';

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  preview: {
    proxy: {},
  },
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:8080',
      '/assets': 'http://127.0.0.1:8080',
      '/static': 'http://127.0.0.1:8080',
    }
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true
  }
});