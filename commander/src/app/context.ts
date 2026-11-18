import { inject } from 'vue'
import type { InjectionKey } from 'vue'
import type { SessionService } from '@/entities/session/service'

export const sessionServiceKey: InjectionKey<SessionService> = Symbol('session-service')

export function useSessionService() {
  const service = inject(sessionServiceKey)
  if (!service) throw new Error('Session service was not provided by the application bootstrap.')
  return service
}
