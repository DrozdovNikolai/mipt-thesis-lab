import { API_BASE_URL } from '@/shared/config/env'
import { endpoints } from './endpoints'
import { HttpClient } from './requestExecutor'
import type { RequestExecutorDeps } from './requestExecutor'

let session: Omit<RequestExecutorDeps, 'baseUrl' | 'refreshPath'> | undefined

export function configureApiSession(deps: Omit<RequestExecutorDeps, 'baseUrl' | 'refreshPath'>) {
  session = deps
}

export const api = new HttpClient({
  baseUrl: API_BASE_URL,
  refreshPath: endpoints.auth.refresh,
  getTokens: () => session?.getTokens() ?? null,
  setTokens: (tokens) => session?.setTokens(tokens),
  clearSession: () => session?.clearSession(),
  getGeneration: () => session?.getGeneration?.() ?? 0,
  reloadTokens: () => session?.reloadTokens?.(),
  withRefreshLock: (action) =>
    session?.withRefreshLock ? session.withRefreshLock(action) : action(),
  onRefreshUnavailable: (error) => session?.onRefreshUnavailable?.(error),
})
