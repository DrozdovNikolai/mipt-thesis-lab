import { defineConfig, devices } from '@playwright/test'
export default defineConfig({
  testDir: './tests/visual',
  fullyParallel: true,
  workers: 4,
  timeout: 45_000,
  outputDir: './test-results/visual',
  reporter: [['list']],
  use: { ...devices['Desktop Chrome'], timezoneId: 'UTC', locale: 'en-US', trace: 'off' },
})
