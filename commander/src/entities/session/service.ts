import type { Pinia } from 'pinia'
import type { QueryClient } from '@tanstack/vue-query'
import { configureApiSession } from '@/shared/api/api'
import { ApiError } from '@/shared/api/requestExecutor'
import type { AuthTokens } from '@/shared/api/requestExecutor'
import { sessionApi } from './api'
import { useSessionStore } from './store'
import {
  browserStorage,
  readPersistedSession,
  SESSION_STORAGE_KEY,
  writePersistedSession,
} from './persistence'

function errorMessage(error: unknown) {
  if (error instanceof ApiError && typeof error.detail === 'string') return error.detail
  return error instanceof Error ? error.message : 'The request failed. Please try again.'
}

function tokenSessionId(token: string): string | null {
  try {
    const payload = token.split('.')[1]
    if (!payload) return null
    const decoded = JSON.parse(atob(payload.replace(/-/g, '+').replace(/_/g, '/')))
    return typeof decoded.sid === 'string' ? decoded.sid : null
  } catch {
    return null
  }
}

export function createSessionService(
  pinia: Pinia,
  queryClient: QueryClient,
  storage: Storage | null = browserStorage(),
) {
  const store = useSessionStore(pinia)
  let persistenceAvailable = storage !== null
  let profileOperation: { generation: number; promise: Promise<void> } | null = null
  let started = false

  function persist() {
    if (storage && persistenceAvailable) {
      persistenceAvailable = writePersistedSession(storage, {
        tokens: store.tokens,
        user: store.user,
        privileges: store.privileges,
      })
    }
  }

  function endSession(write = true) {
    store.startSession(null)
    void queryClient.cancelQueries()
    queryClient.clear()
    if (write) persist()
  }

  function syncFromStorage() {
    if (!storage || !persistenceAvailable) return
    const saved = readPersistedSession(storage)
    if (!saved?.tokens) {
      if (store.tokens) endSession(false)
      return
    }
    if (
      saved.tokens.accessToken === store.tokens?.accessToken &&
      saved.tokens.refreshToken === store.tokens.refreshToken
    )
      return
    const beforeId = store.tokens ? tokenSessionId(store.tokens.accessToken) : null
    const afterId = tokenSessionId(saved.tokens.accessToken)
    const changedUser = saved.user && store.user && saved.user.id !== store.user.id
    if (!store.tokens || changedUser || (beforeId && afterId && beforeId !== afterId)) {
      endSession(false)
      store.startSession(saved.tokens)
    } else {
      store.tokens = saved.tokens
    }
  }

  configureApiSession({
    getTokens: () => store.tokens,
    getGeneration: () => store.generation,
    setTokens: (tokens: AuthTokens) => {
      store.tokens = tokens
      persist()
    },
    clearSession: () => endSession(),
    reloadTokens: syncFromStorage,
    withRefreshLock: async (action) => {
      if (typeof navigator !== 'undefined' && navigator.locks) {
        return await navigator.locks.request('commander-session-refresh', action)
      }
      // Supported production browsers use Web Locks on HTTPS/localhost.
      // Single-page single-flight still applies in an unavailable-storage/legacy environment.
      return await action()
    },
    onRefreshUnavailable: (error) => store.markError(errorMessage(error)),
  })

  async function loadProfile() {
    if (!store.tokens) return
    if (profileOperation?.generation === store.generation) return profileOperation.promise
    const generation = store.generation
    store.status = 'loading-profile'
    store.error = null
    const promise = (async () => {
      try {
        const profile = await sessionApi.me()
        if (generation !== store.generation) return
        store.setUser(profile)
        persist()
      } catch (error) {
        if (generation !== store.generation) return
        if (error instanceof ApiError && error.status === 401) endSession()
        else store.markError(errorMessage(error))
      }
    })().finally(() => {
      if (profileOperation?.promise === promise) profileOperation = null
    })
    profileOperation = { generation, promise }
    return promise
  }

  async function restore() {
    if (!started) {
      started = true
      store.startSession(storage ? (readPersistedSession(storage)?.tokens ?? null) : null)
    }
    if (store.tokens && !store.isReady) await loadProfile()
  }

  async function login(payload: { login: string; password: string }) {
    if (store.status === 'authenticating') return
    endSession()
    const generation = store.generation
    store.status = 'authenticating'
    try {
      const pair = await sessionApi.login(payload)
      if (generation !== store.generation) return
      if (!pair.accessToken || !pair.refreshToken)
        throw new Error('The server returned an invalid session.')
      store.tokens = { accessToken: pair.accessToken, refreshToken: pair.refreshToken }
      persist()
      await loadProfile()
    } catch (error) {
      if (generation !== store.generation) return
      store.status = 'anonymous'
      store.error = errorMessage(error)
    }
  }

  function onStorage(event: StorageEvent) {
    if (event.key !== SESSION_STORAGE_KEY && event.key !== null) return
    syncFromStorage()
    if (store.tokens && !store.isReady) void loadProfile()
  }
  if (typeof window !== 'undefined') window.addEventListener('storage', onStorage)

  return {
    store,
    restore,
    login,
    logout: () => endSession(),
    retry: loadProfile,
    dispose: () => {
      if (typeof window !== 'undefined') window.removeEventListener('storage', onStorage)
    },
  }
}

export type SessionService = ReturnType<typeof createSessionService>
