import { createRouter, createWebHistory } from 'vue-router'
import { PRIVILEGES } from '@/entities/session/privileges'
import AppShell from '@/widgets/layout/AppShell.vue'

export function createAppRouter() {
  return createRouter({
    history: createWebHistory(import.meta.env.BASE_URL),
    routes: [
      {
        path: '/',
        component: AppShell,
        children: [
          { path: '', redirect: '/pilots' },
          {
            path: 'training-sessions',
            component: () => import('@/views/TrainingSessionsView.vue'),
            meta: { privileges: [PRIVILEGES.PILOTS_READ] },
          },
          {
            path: 'training-sessions/:trainingSessionId',
            component: () => import('@/views/TrainingSessionDetailView.vue'),
            meta: { privileges: [PRIVILEGES.PILOTS_READ] },
          },
          {
            path: 'pilots',
            component: () => import('@/views/PilotsView.vue'),
            meta: { privileges: [PRIVILEGES.PILOTS_READ] },
          },
          {
            path: 'pilots/:pilotId',
            component: () => import('@/views/PilotProfileView.vue'),
            meta: { privileges: [PRIVILEGES.PILOTS_READ] },
            children: [
              {
                path: '',
                redirect: (to) =>
                  `/pilots/${encodeURIComponent(String(to.params.pilotId))}/training-data`,
              },
              {
                path: 'training-data',
                component: () => import('@/views/PilotProfileTrainingDataView.vue'),
              },
              { path: 'profile', component: () => import('@/views/PilotProfileInfoView.vue') },
            ],
          },
          {
            path: 'analytics',
            component: () => import('@/views/AnalyticsView.vue'),
            meta: { privileges: [PRIVILEGES.PILOTS_READ] },
          },
          {
            path: 'settings',
            component: () => import('@/views/SettingsView.vue'),
            meta: { privileges: [PRIVILEGES.PILOTS_READ] },
          },
          {
            path: 'compatibility',
            component: () => import('@/views/CompatibilityView.vue'),
            meta: { privileges: [PRIVILEGES.PILOTS_READ] },
          },
          {
            path: 'admin',
            component: () => import('@/views/AdminOnlyView.vue'),
            meta: { privileges: [PRIVILEGES.USERS_READ] },
          },
          { path: 'forbidden', component: () => import('@/views/ForbiddenView.vue') },
          { path: ':pathMatch(.*)*', redirect: '/pilots' },
        ],
      },
    ],
  })
}
