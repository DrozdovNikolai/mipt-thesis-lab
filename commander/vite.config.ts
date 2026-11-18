import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [vue(), tailwindcss()],
  resolve: { alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) } },
  server: {
    proxy: process.env.COMMANDER_API_PROXY
      ? { '/api': { target: process.env.COMMANDER_API_PROXY, changeOrigin: true } }
      : undefined,
  },
})
