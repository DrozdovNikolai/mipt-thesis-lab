import type { RouteLocationNormalized, RouteLocationNormalizedLoaded, Router } from 'vue-router'
import type { SessionService } from '@/entities/session/service'

declare module 'vue-router' {
  interface RouteMeta {
    privileges?: readonly string[]
  }
}

export function routeAllowed(
  route: RouteLocationNormalized | RouteLocationNormalizedLoaded,
  session: SessionService,
) {
  return route.matched.every(
    (record) => !record.meta.privileges || session.store.hasAllPrivileges(record.meta.privileges),
  )
}

export function installSessionGuards(router: Router, session: SessionService) {
  router.beforeEach(async (to) => {
    await session.restore()
    if (!session.store.isReady) return true // App's auth gate keeps RouterView unmounted.
    if (!routeAllowed(to, session)) return { path: '/forbidden', replace: true }
    return true
  })
}
