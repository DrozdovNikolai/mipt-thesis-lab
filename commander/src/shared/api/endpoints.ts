import { API_BASE_URL } from '@/shared/config/env'

export const endpoints = {
  auth: {
    login: '/auth/login',
    refresh: '/auth/refresh',
    me: '/auth/me',
  },
  commander: {
    aircraft: '/commander/aircraft',
    pilots: '/commander/pilots',
    pilotCompatibility: '/commander/pilots/compatibility',
    scenarios: '/commander/scenarios',
    trainingSessions: '/commander/training-sessions',
    flightTypes: '/commander/flight-types',
    competences: '/commander/competences',
    analytics: {
      competenciesGradeDistribution: '/commander/analytics/competencies/grade-distribution',
      competenciesAverageTrend: '/commander/analytics/competencies/average-trend',
      pilotsGradeDistribution: '/commander/analytics/pilots/grade-distribution',
      instructorsGradeDistribution: '/commander/analytics/instructors/grade-distribution',
    },
  },
  ai: {
    scenarioJobs: '/ai/scenario-jobs',
  },
  users: {
    root: '/users',
    positions: '/users/positions',
    recurrentCompliance: '/users/me/recurrent-compliance',
    roles: '/roles',
    privileges: '/privileges',
  },
  training: {
    root: '/training',
    scenarios: '/training/scenarios',
    elements: '/training/elements',
    blocks: '/training/element-blocks',
    folders: '/training/folders',
    folderItems: '/training/folder-items',
    blockFolders: '/training/block-folders',
    blockFolderItems: '/training/block-folder-items',
    modules: '/training/modules',
    exercises: '/training/exercises',
    competences: '/training/competences',
    airlines: '/training/airlines',
    contentSets: '/training/content-sets',
  },
  support: {
    feedback: '/support/feedback',
  },
} as const

export const withBase = (path: string) => `${API_BASE_URL}${path}`
