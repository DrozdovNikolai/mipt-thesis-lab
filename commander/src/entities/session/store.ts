import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import type { AuthTokens } from '@/shared/api/requestExecutor'
import type { SessionUser } from './types'

export type SessionStatus =
  'restoring' | 'anonymous' | 'authenticating' | 'loading-profile' | 'authenticated' | 'error'

export const useSessionStore = defineStore('session', () => {
  const tokens = ref<AuthTokens | null>(null)
  const user = ref<SessionUser | null>(null)
  const status = ref<SessionStatus>('restoring')
  const generation = ref(0)
  const error = ref<string | null>(null)
  const privileges = computed(() => user.value?.privileges ?? [])
  const isReady = computed(() => status.value === 'authenticated' && user.value !== null)

  function startSession(pair: AuthTokens | null) {
    generation.value++
    tokens.value = pair
    user.value = null
    error.value = null
    status.value = pair ? 'loading-profile' : 'anonymous'
  }

  function setUser(profile: SessionUser) {
    user.value = profile
    status.value = 'authenticated'
    error.value = null
  }

  function markError(message: string) {
    user.value = null
    status.value = 'error'
    error.value = message
  }

  function hasPrivilege(privilege: string) {
    return isReady.value && privileges.value.includes(privilege)
  }
  function hasAllPrivileges(required: readonly string[]) {
    return isReady.value && required.every(hasPrivilege)
  }
  function hasAnyPrivilege(required: readonly string[]) {
    return isReady.value && required.some(hasPrivilege)
  }

  return {
    tokens,
    user,
    status,
    generation,
    error,
    privileges,
    isReady,
    startSession,
    setUser,
    markError,
    hasPrivilege,
    hasAllPrivileges,
    hasAnyPrivilege,
  }
})
