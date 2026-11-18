import type { App } from 'vue'
import * as Sentry from '@sentry/vue'
import { APP_BRAND } from '@/shared/branding/brand'

const sampleRate = (value: unknown) => {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? Math.min(1, Math.max(0, parsed)) : 0
}

export function initializeMonitoring(app: App) {
  const dsn = import.meta.env.VITE_SENTRY_DSN as string | undefined
  if (!dsn) return
  Sentry.init({
    app,
    dsn,
    environment: import.meta.env.VITE_APP_ENV || import.meta.env.MODE,
    release: import.meta.env.VITE_APP_VERSION,
    integrations: [Sentry.browserTracingIntegration()],
    tracesSampleRate: sampleRate(import.meta.env.VITE_SENTRY_TRACES_SAMPLE_RATE),
    replaysSessionSampleRate: 0,
    replaysOnErrorSampleRate: sampleRate(import.meta.env.VITE_SENTRY_REPLAYS_ON_ERROR_SAMPLE_RATE),
    beforeSend(event) {
      event.tags = {
        ...event.tags,
        app: 'firefly-commander',
        brand: APP_BRAND.id,
        framework: 'vue',
      }
      return event
    },
  })
}

export { Sentry }
