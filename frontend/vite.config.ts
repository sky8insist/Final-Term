import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import path from 'path';
import {defineConfig} from 'vite';

export default defineConfig(() => {
  return {
    envDir: '..',
    plugins: [react(), tailwindcss()],
    resolve: {
      alias: {
        '@': path.resolve(__dirname, '.'),
      },
    },
    server: {
      port: 5173,
      // Set DISABLE_HMR=true in constrained environments that cannot watch files.
      hmr: process.env.DISABLE_HMR !== 'true',
      // Keep HMR and file watching controlled by the same switch.
      watch: process.env.DISABLE_HMR === 'true' ? null : {},
    },
  };
});
