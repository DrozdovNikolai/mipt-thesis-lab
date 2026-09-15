import { defineConfig, devices } from '@playwright/test'
export default defineConfig({
  testDir: './tests/visual',
  fullyParallel: true,
  workers: 4,
  timeout: 45_000,
  outputDir: './test-results/visual',
  reporter: [['list']],
  webServer: {
    command: 'npm run preview -- --host 127.0.0.1 --port 4177 --strictPort',
    url: 'http://127.0.0.1:4177',
    reuseExistingServer: false,
  },
  use: {
    baseURL: 'http://127.0.0.1:4177',
    ...devices['Desktop Chrome'],
    timezoneId: 'UTC',
    locale: 'en-US',
    trace: 'off',
  },
})
