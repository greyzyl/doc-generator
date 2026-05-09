import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

const devPort = Number(process.env.VITE_DEV_PORT || process.env.FRONTEND_PORT || 62233);
const proxyTarget = process.env.VITE_PROXY_TARGET || process.env.BACKEND_PROXY_TARGET || 'http://127.0.0.1:8009';

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: devPort,
    strictPort: true,
    proxy: {
      '/api': {
        target: proxyTarget,
        changeOrigin: true,
      },
    },
  },
});
