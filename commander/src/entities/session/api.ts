import { api } from '@/shared/api/api'
import { endpoints } from '@/shared/api/endpoints'
import type { TokenPair, SessionUser, UserRecurrentCompliance } from './types'

type LoginPayload = {
  login: string
  password: string
}

export const sessionApi = {
  login: (payload: LoginPayload) =>
    api.post<TokenPair, LoginPayload>(endpoints.auth.login, payload, { auth: false }),
  me: () => api.get<SessionUser>(endpoints.auth.me),
  recurrentCompliance: {
    get: () => api.get<UserRecurrentCompliance>(endpoints.users.recurrentCompliance),
    create: (payload: { complianceId: number }) =>
      api.post<UserRecurrentCompliance, { complianceId: number }>(
        endpoints.users.recurrentCompliance,
        payload,
      ),
    update: (payload: { complianceId: number }) =>
      api.put<UserRecurrentCompliance, { complianceId: number }>(
        endpoints.users.recurrentCompliance,
        payload,
      ),
  },
}
