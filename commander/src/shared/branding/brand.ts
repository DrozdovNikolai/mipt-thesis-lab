export const APP_BRAND = {
  id: '55nord',
  logoLabel: '55NORD Commander',
  documentTitle: '55NORD Commander',
  faviconHref: '/favicon55nord.ico',
  faviconType: 'image/x-icon',
} as const

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

export const applyBranding = () => {
  if (typeof document === 'undefined') {
    return
  }

  document.title = APP_BRAND.documentTitle
  document.documentElement.dataset.brand = APP_BRAND.id

  upsertHeadLink('icon', APP_BRAND.faviconHref, APP_BRAND.faviconType)
  upsertHeadLink('shortcut icon', APP_BRAND.faviconHref, APP_BRAND.faviconType)
}
