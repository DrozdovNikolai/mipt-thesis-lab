import { API_BASE_URL } from '@/shared/config/env'

const browserOrigin =
  typeof window !== 'undefined' && window.location ? window.location.origin : 'http://localhost'

const normalizePathname = (value: string) => {
  if (!value || value === '/') return value
  return value.endsWith('/') ? value.slice(0, -1) : value
}

const apiPrefixPath = (() => {
  try {
    return normalizePathname(new URL(API_BASE_URL, browserOrigin).pathname)
  } catch {
    return ''
  }
})()

export const resolveMediaRequestPath = (rawUrl: string): string => {
  const trimmed = rawUrl.trim()
  if (!trimmed) return trimmed

  try {
    const parsed = new URL(trimmed, browserOrigin)
    const pathWithQuery = `${parsed.pathname}${parsed.search}`

    // Backend stores absolute URL; use API client base host by stripping the api prefix.
    if (
      apiPrefixPath &&
      (pathWithQuery === apiPrefixPath || pathWithQuery.startsWith(`${apiPrefixPath}/`))
    ) {
      const relativePath = pathWithQuery.slice(apiPrefixPath.length)
      return relativePath || '/'
    }

    if (trimmed.startsWith('/')) {
      return pathWithQuery
    }

    return parsed.toString()
  } catch {
    return trimmed
  }
}
