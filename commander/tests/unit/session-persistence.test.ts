import { describe, expect, it } from 'vitest'
import {
  readPersistedSession,
  SESSION_STORAGE_KEY,
  writePersistedSession,
} from '@/entities/session/persistence'

describe('Session persistence', () => {
  it('writes the Zustand v0 envelope and reads the same tokens', () => {
    const state = { tokens: { accessToken: 'a', refreshToken: 'r' }, user: null, privileges: [] }
    expect(writePersistedSession(localStorage, state)).toBe(true)
    expect(JSON.parse(localStorage.getItem(SESSION_STORAGE_KEY)!)).toEqual({ version: 0, state })
    expect(readPersistedSession(localStorage)).toEqual(state)
  })
  it.each([
    'invalid JSON',
    '{}',
    '{"version":1,"state":{}}',
    '{"version":0,"state":{"tokens":{"accessToken":"a"}}}',
    '{"version":0,"state":{"tokens":null}}',
  ])('rejects unusable persisted state %s', (value) => {
    localStorage.setItem(SESSION_STORAGE_KEY, value)
    expect(readPersistedSession(localStorage)).toBeNull()
  })
  it('handles unavailable/quota-limited storage without crashing', () => {
    const storage = {
      getItem: () => {
        throw new Error('denied')
      },
      setItem: () => {
        throw new Error('quota')
      },
    }
    expect(readPersistedSession(storage)).toBeNull()
    expect(writePersistedSession(storage, { tokens: null, user: null, privileges: [] })).toBe(false)
  })
})
