import type { Page, Route } from '@playwright/test'

function emptyPayload(payload: unknown): unknown {
  if (Array.isArray(payload)) return []
  if (!payload || typeof payload !== 'object') return payload
  return Object.fromEntries(Object.entries(payload).map(([key, value]) => [key,
    key === 'latestCompletedTraining' ? null
      : ['total', 'totalPilots', 'totalInstructors', 'pilotsWithCompletedTraining', 'instructorsWithCompletedTraining'].includes(key) ? 0
        : emptyPayload(value),
  ]))
}

/** Transforms only synthetic GET fixture responses, never application code. */
export function visualStatePage(page: Page, state: 'loading' | 'empty' | 'error') {
  let release!: () => void
  const gate = new Promise<void>(resolve => { release = resolve })
  const proxy = new Proxy(page, {
    get(target, property) {
      if (property !== 'route') { const value = Reflect.get(target, property); return typeof value === 'function' ? value.bind(target) : value }
      return (pattern: Parameters<Page['route']>[0], handler: (route: Route) => Promise<unknown>) => target.route(pattern, route => handler(new Proxy(route, {
        get(original, method) {
          if (method !== 'fulfill') { const value = Reflect.get(original, method); return typeof value === 'function' ? value.bind(original) : value }
          return async (options: Parameters<Route['fulfill']>[0]) => {
            const request = original.request()
            if (request.method() !== 'GET' || request.url().includes('/auth/') || !options?.body || !options.contentType?.includes('json')) return original.fulfill(options)
            if (state === 'loading') await gate
            if (state === 'error') return original.fulfill({ status: 503, contentType: 'application/json', body: '{"detail":"Visual fixture unavailable"}' })
            if (state === 'empty') return original.fulfill({ ...options, body: JSON.stringify(emptyPayload(JSON.parse(String(options.body)))) })
            return original.fulfill(options)
          }
        },
      })))
    },
  })
  return { page: proxy, release }
}
