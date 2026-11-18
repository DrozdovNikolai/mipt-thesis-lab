import { API_BASE_URL } from '@/shared/config/env'

export type HttpMethod = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'

export type AuthTokens = {
  accessToken: string
  refreshToken: string
}

export class ApiError extends Error {
  status: number
  detail: unknown
  code?: string

  constructor(status: number, detail: unknown) {
    const extracted = ApiError.extract(detail)
    super(
      extracted.message ??
        (typeof detail === 'string' ? detail : `Request failed with status ${status}`),
    )
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
    this.code = extracted.code
  }

  private static extract(detail: unknown): { message?: string; code?: string } {
    if (!detail || typeof detail !== 'object') return {}

    const candidate = detail as Record<string, unknown>

    // Our backend error envelope: { error: { status, code, message, ... } }
    const envelope = candidate.error
    if (envelope && typeof envelope === 'object') {
      const err = envelope as Record<string, unknown>
      const message = typeof err.message === 'string' ? err.message : undefined
      const code = typeof err.code === 'string' ? err.code : undefined
      return { message, code }
    }

    // Other generic shapes
    const message = typeof candidate.message === 'string' ? candidate.message : undefined
    const code = typeof candidate.code === 'string' ? candidate.code : undefined
    return { message, code }
  }
}

export type RequestConfig<TBody = unknown> = {
  path: string
  method?: HttpMethod
  query?: Record<string, string | number | boolean | undefined>
  body?: TBody
  headers?: Record<string, string>
  responseType?: 'json' | 'text' | 'blob'
  auth?: boolean
  signal?: AbortSignal
}

export type RequestExecutorDeps = {
  baseUrl?: string
  refreshPath: string
  getTokens: () => AuthTokens | null
  setTokens: (tokens: AuthTokens) => void
  clearSession: () => void
  getGeneration?: () => number
  reloadTokens?: () => void
  withRefreshLock?: <T>(action: () => Promise<T>) => Promise<T>
  onRefreshUnavailable?: (error: Error) => void
}

export class HttpClient {
  private readonly baseUrl: string
  private readonly refreshPath: string
  private readonly getTokens: () => AuthTokens | null
  private readonly setTokens: (tokens: AuthTokens) => void
  private readonly clearSession: () => void
  private readonly getGeneration: () => number
  private readonly reloadTokens: () => void
  private readonly withRefreshLock: <T>(action: () => Promise<T>) => Promise<T>
  private readonly onRefreshUnavailable: (error: Error) => void
  private refreshOperation: { generation: number; promise: Promise<AuthTokens | null> } | null =
    null

  constructor(deps: RequestExecutorDeps) {
    this.baseUrl = deps.baseUrl || API_BASE_URL
    this.refreshPath = deps.refreshPath
    this.getTokens = deps.getTokens
    this.setTokens = deps.setTokens
    this.clearSession = deps.clearSession
    this.getGeneration = deps.getGeneration ?? (() => 0)
    this.reloadTokens = deps.reloadTokens ?? (() => {})
    this.withRefreshLock = deps.withRefreshLock ?? ((action) => action())
    this.onRefreshUnavailable = deps.onRefreshUnavailable ?? (() => {})
  }

  private assertCurrent(generation: number) {
    if (generation !== this.getGeneration()) {
      throw new DOMException('The session changed while the request was in progress.', 'AbortError')
    }
  }

  private buildUrl(path: string, query?: Record<string, string | number | boolean | undefined>) {
    const rawUrl = path.startsWith('http') ? path : `${this.baseUrl}${path}`
    const origin =
      typeof window !== 'undefined' && window.location ? window.location.origin : 'http://localhost'
    const url = new URL(rawUrl, origin)
    if (query) {
      Object.entries(query).forEach(([key, value]) => {
        if (value === undefined) return
        url.searchParams.append(key, String(value))
      })
    }
    return url.toString()
  }

  private normalizeTokens(payload: unknown): AuthTokens | null {
    if (!payload || typeof payload !== 'object') return null
    const candidate = payload as Record<string, unknown>
    const access = candidate.accessToken
    const refresh = candidate.refreshToken
    if (typeof access !== 'string' || !access || typeof refresh !== 'string' || !refresh)
      return null
    return { accessToken: access, refreshToken: refresh }
  }

  private parseJsonSafe(text: string) {
    try {
      return JSON.parse(text)
    } catch {
      return text
    }
  }

  private async refreshTokens(tokens: AuthTokens, generation: number): Promise<AuthTokens | null> {
    if (this.refreshOperation?.generation === generation) return this.refreshOperation.promise

    const operation = this.withRefreshLock(async () => {
      this.assertCurrent(generation)
      this.reloadTokens()
      this.assertCurrent(generation)
      const currentTokens = this.getTokens()
      if (!currentTokens) return null
      // Another request or browser tab may have rotated the pair while this one waited.
      if (
        currentTokens.accessToken !== tokens.accessToken ||
        currentTokens.refreshToken !== tokens.refreshToken
      ) {
        return currentTokens
      }
      try {
        const response = await fetch(this.buildUrl(this.refreshPath), {
          method: 'POST',
          headers: {
            Accept: 'application/json',
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({ refreshToken: currentTokens.refreshToken }),
        })

        const payloadText = await response.text()
        const payload = payloadText ? this.parseJsonSafe(payloadText) : null
        this.assertCurrent(generation)

        if (!response.ok) {
          if (response.status === 401 || response.status === 403) {
            this.clearSession()
            return null
          }
          throw new ApiError(response.status, (payload as { detail?: unknown })?.detail ?? payload)
        }

        const normalized = this.normalizeTokens(payload)
        if (!normalized) {
          this.clearSession()
          return null
        }

        this.setTokens(normalized)
        return normalized
      } catch (error) {
        if (
          generation === this.getGeneration() &&
          !(error instanceof DOMException && error.name === 'AbortError')
        ) {
          this.onRefreshUnavailable(error instanceof Error ? error : new Error(String(error)))
        }
        throw error
      }
    })
    const promise = operation.finally(() => {
      if (this.refreshOperation?.promise === promise) this.refreshOperation = null
    })
    this.refreshOperation = { generation, promise }
    return promise
  }

  private async send<TResponse, TBody>(
    config: RequestConfig<TBody>,
    hasRetried = false,
  ): Promise<TResponse> {
    const requiresAuth = config.auth !== false
    const tokens = this.getTokens()
    const generation = this.getGeneration()
    const url = this.buildUrl(config.path, config.query)
    if (
      requiresAuth &&
      tokens &&
      new URL(url).origin !== new URL(this.buildUrl(this.refreshPath)).origin
    ) {
      throw new ApiError(400, {
        code: 'UNTRUSTED_AUTH_ORIGIN',
        message: 'Authenticated requests must use the configured API origin.',
      })
    }

    const headers: Record<string, string> = {
      Accept: config.responseType === 'blob' ? '*/*' : 'application/json',
      ...config.headers,
    }

    let body: BodyInit | undefined
    if (config.body !== undefined) {
      if (config.body instanceof FormData) {
        body = config.body
      } else {
        headers['Content-Type'] ??= 'application/json'
        body = JSON.stringify(config.body)
      }
    }

    if (requiresAuth && tokens?.accessToken) {
      headers.Authorization = `Bearer ${tokens.accessToken}`
    }

    const response = await fetch(url, {
      method: config.method ?? 'GET',
      headers,
      body,
      signal: config.signal,
    })
    if (requiresAuth) this.assertCurrent(generation)

    if (response.status === 401 && requiresAuth && !hasRetried && tokens?.refreshToken) {
      const latestTokens = this.getTokens()
      const refreshed =
        latestTokens && latestTokens.accessToken !== tokens.accessToken
          ? latestTokens
          : await this.refreshTokens(tokens, generation)
      if (refreshed?.accessToken) {
        this.assertCurrent(generation)
        config.signal?.throwIfAborted()
        return this.send<TResponse, TBody>(config, true)
      }
    }

    if (!response.ok) {
      const payloadText = await response.text()
      const payload = payloadText ? this.parseJsonSafe(payloadText) : null
      if (requiresAuth) this.assertCurrent(generation)
      if (requiresAuth && response.status === 401 && generation === this.getGeneration()) {
        this.clearSession()
      }
      throw new ApiError(
        response.status,
        (payload as { detail?: unknown })?.detail ?? payload ?? response.statusText,
      )
    }

    if (config.responseType === 'blob') {
      const blob = await response.blob()
      if (requiresAuth) this.assertCurrent(generation)
      return blob as TResponse
    }

    if (config.responseType === 'text') {
      const text = await response.text()
      if (requiresAuth) this.assertCurrent(generation)
      return text as TResponse
    }

    const payloadText = await response.text()
    const payload = payloadText ? this.parseJsonSafe(payloadText) : null
    if (requiresAuth) this.assertCurrent(generation)
    return payload as TResponse
  }

  request<TResponse = unknown, TBody = unknown>(config: RequestConfig<TBody>) {
    return this.send<TResponse, TBody>(config)
  }

  get<TResponse = unknown>(path: string, config?: Omit<RequestConfig, 'path' | 'method' | 'body'>) {
    return this.request<TResponse>({ ...(config ?? {}), path, method: 'GET' })
  }

  getBlob(path: string, config?: Omit<RequestConfig, 'path' | 'method' | 'body' | 'responseType'>) {
    return this.request<Blob>({ ...(config ?? {}), path, method: 'GET', responseType: 'blob' })
  }

  post<TResponse = unknown, TBody = unknown>(
    path: string,
    body?: TBody,
    config?: Omit<RequestConfig<TBody>, 'path' | 'method' | 'body'>,
  ) {
    return this.request<TResponse, TBody>({ ...(config ?? {}), path, method: 'POST', body })
  }

  put<TResponse = unknown, TBody = unknown>(
    path: string,
    body?: TBody,
    config?: Omit<RequestConfig<TBody>, 'path' | 'method' | 'body'>,
  ) {
    return this.request<TResponse, TBody>({ ...(config ?? {}), path, method: 'PUT', body })
  }

  patch<TResponse = unknown, TBody = unknown>(
    path: string,
    body?: TBody,
    config?: Omit<RequestConfig<TBody>, 'path' | 'method' | 'body'>,
  ) {
    return this.request<TResponse, TBody>({ ...(config ?? {}), path, method: 'PATCH', body })
  }

  delete<TResponse = unknown, TBody = unknown>(
    path: string,
    config?: Omit<RequestConfig<TBody>, 'path' | 'method' | 'body'>,
  ) {
    return this.request<TResponse, TBody>({ ...(config ?? {}), path, method: 'DELETE' })
  }
}
