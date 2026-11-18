import { computed } from 'vue'
import { useSessionStore } from './store'
import type { SessionScope } from '@/entities/commander/queryKeys'

export function useSessionScope() {
  const session = useSessionStore()
  return computed<SessionScope>(() => [session.user?.id ?? null, session.user?.airlineId ?? null])
}
