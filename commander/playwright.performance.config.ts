import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: './tests/performance',
  workers: 1,
  timeout: 120_000,
  outputDir: './test-results/performance',
  reporter: [['list']],
  use: { ...devices['Desktop Chrome'], timezoneId: 'UTC', locale: 'en-US', trace: 'off' },
})
