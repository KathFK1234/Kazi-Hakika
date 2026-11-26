/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react'
import { defineConfig, type Plugin } from 'vite'

// FastAPI fills these from APP_NAME/APP_TAGLINE when it serves the build.
// The dev server has no FastAPI in front of index.html, so fill in defaults.
function devPlaceholders(): Plugin {
  return {
    name: 'kazi-dev-placeholders',
    apply: 'serve',
    transformIndexHtml: (html) =>
      html
        .replaceAll('__APP_NAME__', 'Kazi Hakika')
        .replaceAll('__APP_TAGLINE__', 'verified roles, tracked your way.'),
  }
}

// The build goes straight into the FastAPI package, which serves it.
export default defineConfig({
  plugins: [react(), devPlaceholders()],
  build: {
    outDir: '../app/static',
    emptyOutDir: true,
    sourcemap: false,
    // Never inline fonts as data: URIs; CSP font-src 'self' would block them.
    assetsInlineLimit: (file) => (file.endsWith('.woff2') || file.endsWith('.woff') ? false : undefined),
  },
  server: {
    proxy: {
      '/api': 'http://localhost:8000',
      '/health': 'http://localhost:8000',
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    restoreMocks: true,
    unstubGlobals: true,
  },
})
