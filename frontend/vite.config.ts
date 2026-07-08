import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 3000,
    strictPort: true,
    watch: {
      usePolling: true
    },
    hmr: {
      clientPort: 3000,
      // Geliştirici makinenizin LAN IP'sini gerekirse VITE_HMR_HOST ile geçin
      // (örn. VITE_HMR_HOST=192.168.1.10 npm run dev). Belirtilmezse Vite
      // varsayılan davranışına (istek yapılan host) düşer.
      ...(process.env.VITE_HMR_HOST ? { host: process.env.VITE_HMR_HOST } : {})
    }
  }
})
