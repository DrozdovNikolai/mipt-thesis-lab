// @vitest-environment node
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, HttpClient } from '@/shared/api/requestExecutor'
import type { AuthTokens } from '@/shared/api/requestExecutor'

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => {
    resolve = done
  })
  return { promise, resolve }
}
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

function setup() {
  const state: { tokens: AuthTokens | null; generation: number } = {
    tokens: { accessToken: 'old', refreshToken: 'old-refresh' },
    generation: 0,
  }
  const clearSession = vi.fn(() => {
    state.tokens = null
    state.generation++
  })
  const setTokens = vi.fn((tokens: AuthTokens) => {
    state.tokens = tokens
  })
  const unavailable = vi.fn()
  const client = new HttpClient({
    baseUrl: 'https://api.example.test/api',
    refreshPath: '/auth/refresh',
    getTokens: () => state.tokens,
    getGeneration: () => state.generation,
    clearSession,
    setTokens,
    onRefreshUnavailable: unavailable,
  })
  const fetch = vi.fn<typeof globalThis.fetch>()
  vi.stubGlobal('fetch', fetch)
  return { client, state, clearSession, setTokens, unavailable, fetch }
}
afterEach(() => vi.unstubAllGlobals())

describe('HTTP contract', () => {
  it('preserves false, zero, empty strings, skips undefined and sends a bearer', async () => {
    const { client, fetch } = setup()
    fetch.mockResolvedValue(json({ items: [] }))
    await client.get('/pilots', { query: { isActive: false, offset: 0, q: '', absent: undefined } })
    const [url, options] = fetch.mock.calls[0]!
    expect(String(url)).toBe('https://api.example.test/api/pilots?isActive=false&offset=0&q=')
    expect(options?.headers).toMatchObject({ Authorization: 'Bearer old' })
  })

  it('keeps multipart boundaries native and accepts empty success', async () => {
    const { client, fetch } = setup()
    fetch.mockResolvedValue(new Response(null, { status: 204 }))
    const form = new FormData()
    form.set('name', 'example')
    expect(await client.post('/upload', form)).toBeNull()
    expect(fetch.mock.calls[0]![1]?.body).toBe(form)
    expect(fetch.mock.calls[0]![1]?.headers).not.toHaveProperty('Content-Type')
  })

  it('parses backend errors and does not clear a different session on public login 401', async () => {
    const { client, fetch, clearSession } = setup()
    fetch.mockResolvedValue(
      json({ detail: { error: { code: 'BAD_LOGIN', message: 'Invalid credentials' } } }, 401),
    )
    await expect(
      client.post('/auth/login', { login: 'x', password: 'y' }, { auth: false }),
    ).rejects.toMatchObject({ status: 401, code: 'BAD_LOGIN', message: 'Invalid credentials' })
    expect(clearSession).not.toHaveBeenCalled()
    expect(fetch.mock.calls[0]![1]?.headers).not.toHaveProperty('Authorization')
  })

  it('does not send the bearer to a foreign media origin', async () => {
    const { client, fetch } = setup()
    await expect(client.getBlob('https://untrusted.example/photo.png')).rejects.toMatchObject({
      code: 'UNTRUSTED_AUTH_ORIGIN',
    })
    expect(fetch).not.toHaveBeenCalled()
  })

  it.each([
    {
      payload: { detail: 'Permission denied' },
      status: 403,
      message: 'Permission denied',
      code: undefined,
      detail: 'Permission denied',
    },
    {
      payload: { error: { code: 'REJECTED', message: 'Threshold rejected' } },
      status: 422,
      message: 'Threshold rejected',
      code: 'REJECTED',
      detail: { error: { code: 'REJECTED', message: 'Threshold rejected' } },
    },
  ])(
    'preserves status and message for a $status API envelope',
    async ({ payload, status, message, code, detail }) => {
      const { client, fetch } = setup()
      fetch.mockResolvedValue(json(payload, status))
      await expect(client.get('/commander/flight-types')).rejects.toMatchObject({
        status,
        message,
        code,
        detail,
      })
    },
  )

  it('retains a Blob response and forwards cancellation', async () => {
    const { client, fetch } = setup()
    const controller = new AbortController()
    fetch.mockResolvedValue(
      new Response('%PDF-test', { headers: { 'Content-Type': 'application/pdf' } }),
    )
    const blob = await client.getBlob('/report.pdf', { signal: controller.signal })
    expect(await blob.text()).toBe('%PDF-test')
    expect(fetch.mock.calls[0]![1]?.signal).toBe(controller.signal)
  })
})

describe('session concurrency', () => {
  it.each([null, {}, { accessToken: 'new', refreshToken: '' }])(
    'ends a successful refresh with unusable payload %j',
    async (payload) => {
      const { client, fetch, state, clearSession, setTokens } = setup()
      fetch.mockImplementation(async (url) =>
        String(url).endsWith('/auth/refresh') ? json(payload) : json({}, 401),
      )
      await expect(client.get('/pilots')).rejects.toMatchObject({ name: 'AbortError' })
      expect(clearSession).toHaveBeenCalledTimes(1)
      expect(setTokens).not.toHaveBeenCalled()
      expect(state.tokens).toBeNull()
    },
  )
  it('shares one refresh for simultaneous 401 responses', async () => {
    const { client, fetch, setTokens } = setup()
    const refresh = deferred<Response>()
    fetch.mockImplementation(async (url, options) => {
      if (String(url).endsWith('/auth/refresh')) return refresh.promise
      return (options?.headers as Record<string, string>).Authorization === 'Bearer old'
        ? json({}, 401)
        : json({ ok: true })
    })
    const first = client.get('/one')
    const second = client.get('/two')
    await vi.waitFor(() =>
      expect(
        fetch.mock.calls.filter(([url]) => String(url).endsWith('/auth/refresh')),
      ).toHaveLength(1),
    )
    refresh.resolve(json({ accessToken: 'new', refreshToken: 'new-refresh' }))
    expect(await Promise.all([first, second])).toEqual([{ ok: true }, { ok: true }])
    expect(setTokens).toHaveBeenCalledTimes(1)
    expect(fetch).toHaveBeenCalledTimes(5)
  })

  it('retries a delayed 401 using the already rotated pair without refreshing twice', async () => {
    const { client, fetch } = setup()
    const slow = deferred<Response>()
    fetch.mockImplementation(async (url, options) => {
      if (String(url).endsWith('/auth/refresh'))
        return json({ accessToken: 'new', refreshToken: 'new-refresh' })
      if ((options?.headers as Record<string, string>).Authorization === 'Bearer new')
        return json({ ok: true })
      return String(url).endsWith('/slow') ? slow.promise : json({}, 401)
    })
    const first = client.get('/slow')
    await client.get('/fast')
    slow.resolve(json({}, 401))
    expect(await first).toEqual({ ok: true })
    expect(fetch.mock.calls.filter(([url]) => String(url).endsWith('/auth/refresh'))).toHaveLength(
      1,
    )
  })

  it('does not restore tokens after logout during refresh', async () => {
    const { client, fetch, state, setTokens } = setup()
    const refresh = deferred<Response>()
    fetch.mockImplementation(async (url) =>
      String(url).endsWith('/auth/refresh') ? refresh.promise : json({}, 401),
    )
    const pending = client.get('/pilots')
    const outcome = expect(pending).rejects.toMatchObject({ name: 'AbortError' })
    await vi.waitFor(() => expect(fetch).toHaveBeenCalledTimes(2))
    state.tokens = null
    state.generation++
    refresh.resolve(json({ accessToken: 'late', refreshToken: 'late-refresh' }))
    await outcome
    expect(setTokens).not.toHaveBeenCalled()
    expect(state.tokens).toBeNull()
  })

  it.each([
    { path: '/auth/me', method: 'GET', responseType: undefined },
    { path: '/commander/flight-types/1', method: 'PUT', responseType: undefined },
    { path: '/media/photo.png', method: 'GET', responseType: 'blob' },
  ] as const)('rejects an old $method $path response after switching users', async (config) => {
    const { client, fetch, state } = setup()
    const response = deferred<Response>()
    fetch.mockReturnValue(response.promise)
    const pending = client.request(config)
    const outcome = expect(pending).rejects.toMatchObject({ name: 'AbortError' })
    state.generation++
    state.tokens = { accessToken: 'other', refreshToken: 'other-refresh' }
    response.resolve(json({ private: 'previous user' }))
    await outcome
  })

  it('ends rejected refresh, but retains tokens after a temporary refresh failure', async () => {
    const { client, fetch, state, clearSession, unavailable } = setup()
    fetch.mockImplementation(async (url) =>
      json({}, String(url).endsWith('/auth/refresh') ? 503 : 401),
    )
    await expect(client.get('/pilots')).rejects.toBeInstanceOf(ApiError)
    expect(state.tokens?.accessToken).toBe('old')
    expect(clearSession).not.toHaveBeenCalled()
    expect(unavailable).toHaveBeenCalledTimes(1)
    fetch.mockImplementation(async () => json({}, 401))
    await expect(client.get('/pilots')).rejects.toMatchObject({ name: 'AbortError' })
    expect(state.tokens).toBeNull()
    expect(clearSession).toHaveBeenCalledTimes(1)
  })

  it('reads tokens again under the cross-tab lock before rotating', async () => {
    const { state, fetch } = setup()
    const lock = vi.fn()
    const client = new HttpClient({
      baseUrl: 'https://api.example.test/api',
      refreshPath: '/auth/refresh',
      getTokens: () => state.tokens,
      setTokens: vi.fn(),
      clearSession: vi.fn(),
      getGeneration: () => state.generation,
      withRefreshLock: async (action) => {
        lock()
        return await action()
      },
      reloadTokens: () => {
        state.tokens = { accessToken: 'other-tab', refreshToken: 'rotated' }
      },
    })
    fetch.mockResolvedValueOnce(json({}, 401)).mockResolvedValueOnce(json({ ok: true }))
    expect(await client.get('/pilots')).toEqual({ ok: true })
    expect(lock).toHaveBeenCalledTimes(1)
    expect(fetch).toHaveBeenCalledTimes(2)
    expect(fetch.mock.calls[1]![1]?.headers).toMatchObject({ Authorization: 'Bearer other-tab' })
  })
})
