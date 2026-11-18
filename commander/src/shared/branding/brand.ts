export type AppBrandId = 'firefly' | '55nord'

type BrandConfig = {
  id: AppBrandId
  displayName: string
  logoLabel: string
  documentTitle: string
  faviconHref: string
  faviconType: string
  logoSrc?: string
}

const BRAND_CONFIGS: Record<AppBrandId, BrandConfig> = {
  firefly: {
    id: 'firefly',
    displayName: 'Firefly',
    logoLabel: 'Firefly Commander',
    documentTitle: 'Firefly Commander',
    faviconHref: '/favicon.png',
    faviconType: 'image/png',
    logoSrc: '/logo.svg',
  },
  '55nord': {
    id: '55nord',
    displayName: '55NORD',
    logoLabel: '55NORD Commander',
    documentTitle: '55NORD Commander',
    faviconHref: '/favicon55nord.ico',
    faviconType: 'image/x-icon',
  },
}

const resolveBrandId = (rawValue: string | undefined): AppBrandId => {
  const normalizedValue = rawValue?.trim().toLowerCase()
  if (normalizedValue === '55nord' || normalizedValue === 'ru') {
    return '55nord'
  }
  return 'firefly'
}

const upsertHeadLink = (rel: string, href: string, type: string) => {
  let link = document.head.querySelector<HTMLLinkElement>(`link[rel="${rel}"]`)
  if (link === null) {
    link = document.createElement('link')
    link.rel = rel
    document.head.append(link)
  }
  link.href = href
  link.type = type
}

export const APP_BRAND =
  BRAND_CONFIGS[resolveBrandId((import.meta.env.VITE_APP_BRAND as string | undefined) ?? '55nord')]

export const applyBranding = () => {
  if (typeof document === 'undefined') {
    return
  }

  document.title = APP_BRAND.documentTitle
  document.documentElement.dataset.brand = APP_BRAND.id

  upsertHeadLink('icon', APP_BRAND.faviconHref, APP_BRAND.faviconType)
  upsertHeadLink('shortcut icon', APP_BRAND.faviconHref, APP_BRAND.faviconType)
}
