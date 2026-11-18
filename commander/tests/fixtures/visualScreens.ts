import type { Page } from '@playwright/test'
import { installPilotsFixtures } from './pilots'
import { installProfileFixtures } from './profile'
import { installAnalyticsFixtures } from './analytics'
import { installTrainingSessionsFixtures } from './trainingSessions'
import { installMockApi } from './mockApi'

export const screens: {
  name: string
  path: string
  ready: string
  fixture: (page: Page) => Promise<unknown>
}[] = [
  { name: 'pilots', path: '/pilots', ready: 'Pilots', fixture: installPilotsFixtures },
  {
    name: 'profile',
    path: '/pilots/pilot-1/profile',
    ready: 'Alice Alpha',
    fixture: installProfileFixtures,
  },
  {
    name: 'training-data',
    path: '/pilots/pilot-1/training-data',
    ready: 'Alice Alpha',
    fixture: installProfileFixtures,
  },
  {
    name: 'training-sessions',
    path: '/training-sessions',
    ready: 'Training sessions',
    fixture: installTrainingSessionsFixtures,
  },
  {
    name: 'detail',
    path: '/training-sessions/102',
    ready: 'Scenario Bravo',
    fixture: installTrainingSessionsFixtures,
  },
  { name: 'analytics', path: '/analytics', ready: 'Analytics', fixture: installAnalyticsFixtures },
  { name: 'settings', path: '/settings', ready: 'Settings', fixture: installMockApi },
  {
    name: 'compatibility',
    path: '/compatibility',
    ready: 'Compatibility',
    fixture: installMockApi,
  },
]
