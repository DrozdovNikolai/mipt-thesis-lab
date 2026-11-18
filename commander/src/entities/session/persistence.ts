import type { AuthTokens } from '@/shared/api/requestExecutor'
import type { SessionUser } from './types'

export const SESSION_STORAGE_KEY = 'session-store'
export type PersistedSession = {
  tokens: AuthTokens | null
  user: SessionUser | null
  privileges: string[]
}

export function readPersistedSession(storage: Pick<Storage, 'getItem'>): PersistedSession | null {
  try {
    const raw = storage.getItem(SESSION_STORAGE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw)
    if (parsed?.version !== 0 || !parsed.state || typeof parsed.state !== 'object') return null
    const tokens = parsed.state.tokens
    if (
      !tokens ||
      typeof tokens.accessToken !== 'string' ||
      !tokens.accessToken ||
      typeof tokens.refreshToken !== 'string' ||
      !tokens.refreshToken
    )
      return null
    // Persisted user/privileges are never used to grant access. /me is authoritative.
    const user = parsed.state.user
    return {
      tokens: { accessToken: tokens.accessToken, refreshToken: tokens.refreshToken },
      user: user && typeof user.id === 'string' ? (user as SessionUser) : null,
      privileges: Array.isArray(parsed.state.privileges)
        ? parsed.state.privileges.filter((v: unknown) => typeof v === 'string')
        : [],
    }
  } catch {
    return null
  }
}

export function writePersistedSession(
  storage: Pick<Storage, 'setItem'>,
  state: PersistedSession,
): boolean {
  try {
    storage.setItem(SESSION_STORAGE_KEY, JSON.stringify({ state, version: 0 }))
    return true
  } catch {
    return false
  }
}

export function browserStorage(): Storage | null {
  try {
    return window.localStorage
  } catch {
    return null
  }
}
