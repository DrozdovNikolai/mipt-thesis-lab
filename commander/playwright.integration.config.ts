import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: './tests/integration',
  workers: 1,
  outputDir: './test-results/integration',
  retries: 0,
  timeout: 60_000,
  reporter: [['list']],
  use: {
    baseURL: process.env.COMMANDER_INTEGRATION_URL || 'http://127.0.0.1:8088',
    ...devices['Desktop Chrome'],
    // Real session credentials must not enter retained traces or reports.
    trace: 'off',
    screenshot: 'off',
    video: 'off',
  },
})
