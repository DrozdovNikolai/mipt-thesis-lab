import { ApiError } from '@/shared/api/requestExecutor'

export function getErrorMessage(
  error: unknown,
  fallback = 'The request failed. Please try again.',
): string {
  if (error instanceof ApiError && typeof error.detail === 'string') return error.detail
  if (error instanceof Error && error.message) return error.message
  return fallback
}
