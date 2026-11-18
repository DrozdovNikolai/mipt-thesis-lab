import { defineConfig, devices } from '@playwright/test'

const port = Number(process.env.COMMANDER_TEST_PORT || 4175)
const externalBaseUrl = process.env.COMMANDER_TEST_BASE_URL

export default defineConfig({
  testDir: './tests/e2e',
  outputDir: './test-results/chromium',
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL: externalBaseUrl || `http://127.0.0.1:${port}`,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    timezoneId: 'UTC',
    locale: 'en-US',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: externalBaseUrl
    ? undefined
    : {
        command: `npm run ${process.env.COMMANDER_TEST_PREVIEW ? 'preview' : 'dev'} -- --host 127.0.0.1 --port ${port} --strictPort`,
        url: `http://127.0.0.1:${port}`,
        reuseExistingServer: false,
        env: { ...process.env, VITE_API_URL: '/api', VITE_SENTRY_DSN: '' },
      },
})
