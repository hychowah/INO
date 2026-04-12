import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
export default defineConfig({
    plugins: [react()],
    server: {
        port: 5173,
        proxy: {
            '/api': 'http://127.0.0.1:8080',
            '/assets': 'http://127.0.0.1:8080',
            '/static': 'http://127.0.0.1:8080',
            '/concept': 'http://127.0.0.1:8080',
            '/concepts': 'http://127.0.0.1:8080',
            '/topic': 'http://127.0.0.1:8080',
            '/topics': 'http://127.0.0.1:8080',
            '/graph': 'http://127.0.0.1:8080',
            '/reviews': 'http://127.0.0.1:8080',
            '/forecast': 'http://127.0.0.1:8080',
            '/actions': 'http://127.0.0.1:8080'
        }
    },
    build: {
        outDir: 'dist',
        emptyOutDir: true
    }
});
