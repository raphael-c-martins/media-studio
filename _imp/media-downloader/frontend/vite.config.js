import { defineConfig } from 'vite';

export default defineConfig({
  server: {
    port: 3030,
    host: true,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8800',
        changeOrigin: true,
      },
      '/health': {
        target: 'http://127.0.0.1:8800',
        changeOrigin: true,
      }
    }
  }
});
