import { defineConfig } from 'vitest/config'

export default defineConfig({
  test: {
    projects: [
      { test: { name: 'unit', include: ['src/**/*.test.ts'] } },
      { test: { name: 'slow', include: ['e2e/**/*.test.ts'] } },
    ],
  },
})
