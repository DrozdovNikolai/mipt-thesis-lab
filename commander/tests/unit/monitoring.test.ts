import { afterEach, describe, expect, it, vi } from 'vitest'
import { createApp } from 'vue'
import { initializeMonitoring } from '@/shared/monitoring/sentry'

const init = vi.hoisted(() => vi.fn())
vi.mock('@sentry/vue', () => ({ init, browserTracingIntegration: () => ({ name: 'Tracing' }) }))
afterEach(() => {
  init.mockReset()
  vi.unstubAllEnvs()
})
describe('release monitoring', () => {
  it('does not initialize telemetry without a DSN', () => {
    vi.stubEnv('VITE_SENTRY_DSN', '')
    initializeMonitoring(createApp({}))
    expect(init).not.toHaveBeenCalled()
  })
  it('adds release, environment, brand and framework without enabling default sampling', () => {
    vi.stubEnv('VITE_SENTRY_DSN', 'https://public@example.invalid/1')
    vi.stubEnv('VITE_APP_VERSION', 'synthetic-release')
    vi.stubEnv('VITE_APP_ENV', 'staging')
    vi.stubEnv('VITE_SENTRY_TRACES_SAMPLE_RATE', '')
    vi.stubEnv('VITE_SENTRY_REPLAYS_ON_ERROR_SAMPLE_RATE', '')
    initializeMonitoring(createApp({}))
    const options = init.mock.calls[0]![0]
    expect(options).toMatchObject({
      release: 'synthetic-release',
      environment: 'staging',
      tracesSampleRate: 0,
      replaysSessionSampleRate: 0,
      replaysOnErrorSampleRate: 0,
    })
    expect(options.beforeSend({ tags: { existing: 'preserved' } }).tags).toMatchObject({
      existing: 'preserved',
      app: 'firefly-commander',
      brand: '55nord',
      framework: 'vue',
    })
  })
})
