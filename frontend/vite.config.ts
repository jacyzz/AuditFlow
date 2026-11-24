import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'node:path'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:8787',
    },
  },
  build: {
    outDir: path.resolve(__dirname, '../src/auditflow/ui/dist'),
    emptyOutDir: true,
    rollupOptions: {
      output: {
        manualChunks: {
          reactflow: ['@xyflow/react'],
          codemirror: ['@uiw/react-codemirror', '@codemirror/lang-markdown', '@codemirror/lang-yaml', '@codemirror/theme-one-dark'],
        },
      },
    },
  },
})
