import { defineConfig } from 'vitest/config'

// Separate from vite.config.js so tests run without the React/Tailwind plugins.
export default defineConfig({ test: { environment: 'node', include: ['src/**/*.test.js'] } })
