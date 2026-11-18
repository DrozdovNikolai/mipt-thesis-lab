import { createApp, h } from 'vue'
import { createPinia } from 'pinia'
import { VueQueryPlugin } from '@tanstack/vue-query'
import App from './App.vue'
import ErrorBoundary from '@/shared/ui/ErrorBoundary.vue'
import { createQueryClient } from '@/app/providers/queryClient'
import { createSessionService } from '@/entities/session/service'
import { sessionServiceKey } from '@/app/context'
import { createAppRouter } from '@/app/router'
import { installSessionGuards } from '@/app/guards'
import { i18n } from '@/shared/i18n'
import { initializeMonitoring } from '@/shared/monitoring/sentry'
import { applyBranding } from '@/shared/branding/brand'
import './styles.css'

applyBranding()
const pinia = createPinia()
const queryClient = createQueryClient()
const session = createSessionService(pinia, queryClient)
const router = createAppRouter()
installSessionGuards(router, session)
const app = createApp({ render: () => h(ErrorBoundary, null, { default: () => h(App) }) })
app.use(pinia).use(VueQueryPlugin, { queryClient }).use(i18n).use(router)
app.provide(sessionServiceKey, session)
initializeMonitoring(app)
void router.isReady().then(() => app.mount('#app'))

if (import.meta.hot) import.meta.hot.dispose(() => session.dispose())
