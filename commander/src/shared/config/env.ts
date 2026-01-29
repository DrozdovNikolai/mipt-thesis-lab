const fallbackApiUrl = '/api'

export const API_BASE_URL = (import.meta.env.VITE_API_URL as string | undefined) || fallbackApiUrl
export const IS_DEV = Boolean(import.meta.env.DEV)
