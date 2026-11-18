import type { AuthTokens } from '@/shared/api/requestExecutor'
import type { TokenPair } from './types'

export const toAuthTokens = (tokens: TokenPair): AuthTokens => ({
  accessToken: tokens.accessToken,
  refreshToken: tokens.refreshToken,
})
