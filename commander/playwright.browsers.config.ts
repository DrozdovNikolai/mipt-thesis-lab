import { defineConfig, devices } from '@playwright/test'
const externalBaseURL = process.env.COMMANDER_TEST_BASE_URL
export default defineConfig({
  testDir: './tests/e2e',
  testMatch: [
    'session-routes.spec.ts',
    'pilots-avatar-route.spec.ts',
    'settings-compatibility.spec.ts',
    'analytics-layout.spec.ts',
    'acceptance-edges.spec.ts',
  ],
  workers: 2,
  outputDir: './test-results/browsers',
  reporter: [['list']],
  use: {
    baseURL: externalBaseURL || 'http://127.0.0.1:4180',
    trace: 'retain-on-failure',
  },
  webServer: externalBaseURL
    ? undefined
    : {
        command: 'npm run preview -- --host 127.0.0.1 --port 4180 --strictPort',
        url: 'http://127.0.0.1:4180',
        reuseExistingServer: false,
      },
  projects: [
    { name: 'firefox', use: { ...devices['Desktop Firefox'] } },
    {
      name: 'webkit',
      use: {
        ...devices['Desktop Safari'],
        launchOptions: process.env.COMMANDER_WEBKIT_EXECUTABLE
          ? { executablePath: process.env.COMMANDER_WEBKIT_EXECUTABLE }
          : undefined,
      },
    },
  ],
})
