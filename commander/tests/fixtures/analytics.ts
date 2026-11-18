// Fixtures extracted from the verified React baseline: analytics-layout.spec.ts
// Source SHA-256: 420e75c4a95951b9f8f5e7fc137ad3ffca4291707ccf10dfe276d3058d160b33
import type { Page } from '@playwright/test'

type MockUserOverrides = {
  id: string
  login: string
  email: string
  firstName: string | null
  lastName: string | null
  aircraftCodes: string[]
  position?: string | null
}

const makeMockUser = ({
  id,
  login,
  email,
  firstName,
  lastName,
  aircraftCodes,
  position = null,
}: MockUserOverrides) => ({
  id,
  login,
  email,
  isActive: true,
  mustChangePassword: false,
  createdAt: '2026-01-01T00:00:00.000Z',
  firstName,
  lastName,
  position,
  licenseNumber: null,
  phone: null,
  photoUrl: null,
  signatureUrl: null,
  airlineId: 1,
  roles: [],
  privileges: ['pilots:read'],
  aircraftIds: [1],
  aircraftCodes,
})

const mockGradeBuckets = [
  {
    gradeCode: '1',
    gradeLabel: 'Below standard',
    gradeScoreNumeric: 1,
    gradeColorHex: '#dc2626',
  },
  {
    gradeCode: '2',
    gradeLabel: 'Standard',
    gradeScoreNumeric: 2,
    gradeColorHex: '#2563eb',
  },
  {
    gradeCode: '3',
    gradeLabel: 'Above standard',
    gradeScoreNumeric: 3,
    gradeColorHex: '#0f766e',
  },
]

export async function installAnalyticsFixtures(page: Page) {

  // Complete the old layout-only fixture for visual and four-query regression.
  await page.route('**/api/commander/pilots**', route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ total: 0, limit: 10, offset: 0, items: [] }) }))
  await page.route('**/api/commander/analytics/competencies/average-trend**', route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({
    totalPilots: 6, pilotsWithCompletedTraining: 6, filters: {}, items: [{ competenceId: 1, competenceCode: 'OPS', competenceName: 'Operations', orderIndex: 1, points: [
      { periodStart: '2025-01-01', periodEnd: '2025-06-30', periodLabel: 'H1 2025', averageScoreNumeric: '3.5', pilotCount: 4 },
      { periodStart: '2025-07-01', periodEnd: '2025-12-31', periodLabel: 'H2 2025', averageScoreNumeric: '4.1', pilotCount: 6 },
    ] }],
  }) }))

  await page.setViewportSize({ width: 1024, height: 768 })

  await page.route('**/api/auth/login', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        tokenType: 'Bearer',
        accessToken: 'test-access-token',
        refreshToken: 'test-refresh-token',
      }),
    })
  })

  await page.route('**/api/auth/me', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(
        makeMockUser({
          id: '1',
          login: 'admin',
          email: 'admin@example.com',
          firstName: 'Admin',
          lastName: 'User',
          aircraftCodes: ['B737'],
        }),
      ),
    })
  })

  await page.route('**/api/training/aircraft**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([
        { id: 1, code: 'B737', name: 'Boeing 737 Long Production Aircraft Name', active: true, airlineId: 1 },
      ]),
    })
  })

  await page.route('**/api/users/positions**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([
        { id: 1, name: 'Captain', airlineId: 1 },
        { id: 2, name: 'First Officer', airlineId: 1 },
      ]),
    })
  })

  await page.route('**/api/commander/analytics/competencies/grade-distribution**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        totalPilots: 8,
        pilotsWithCompletedTraining: 6,
        filters: {
          aircraftId: null,
          ageYears: null,
          positionId: null,
          asOfDate: null,
        },
        items: [
          {
            competenceId: 1,
            competenceCode: 'OPS',
            competenceName: 'Operations',
            orderIndex: 1,
            assessedPilotCount: 6,
            grades: mockGradeBuckets.map((grade, index) => ({
              ...grade,
              pilotCount: 2 + index,
            })),
          },
          {
            competenceId: 2,
            competenceCode: 'CRM',
            competenceName: 'Crew Resource Management',
            orderIndex: 2,
            assessedPilotCount: 6,
            grades: mockGradeBuckets.map((grade, index) => ({
              ...grade,
              pilotCount: 1 + index,
            })),
          },
        ],
      }),
    })
  })

  await page.route('**/api/commander/analytics/pilots/grade-distribution**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        totalPilots: 8,
        pilotsWithCompletedTraining: 6,
        filters: {
          aircraftId: null,
          ageYears: null,
          positionId: null,
          asOfDate: null,
        },
        items: [
          {
            pilotId: 'pilot-1',
            firstName: 'Anna',
            lastName: 'Taylor',
            assessedGradeCount: 6,
            grades: mockGradeBuckets.map((grade, index) => ({
              ...grade,
              gradeCount: 1 + index,
            })),
          },
          {
            pilotId: 'pilot-2',
            firstName: 'John',
            lastName: 'Miller',
            assessedGradeCount: 6,
            grades: mockGradeBuckets.map((grade, index) => ({
              ...grade,
              gradeCount: 2 + index,
            })),
          },
          {
            pilotId: 'pilot-3',
            firstName: 'Kate',
            lastName: 'Lopez',
            assessedGradeCount: 6,
            grades: mockGradeBuckets.map((grade, index) => ({
              ...grade,
              gradeCount: 1 + index,
            })),
          },
        ],
      }),
    })
  })

  await page.route('**/api/commander/analytics/instructors/grade-distribution**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        totalInstructors: 4,
        instructorsWithCompletedTraining: 3,
        filters: {
          aircraftId: null,
          ageYears: null,
          positionId: null,
          asOfDate: null,
        },
        items: [
          {
            instructorId: 'instructor-1',
            firstName: 'Maria',
            lastName: 'Stone',
            assessedGradeCount: 6,
            grades: mockGradeBuckets.map((grade, index) => ({
              ...grade,
              gradeCount: 2 + index,
            })),
          },
          {
            instructorId: 'instructor-2',
            firstName: 'David',
            lastName: 'Clark',
            assessedGradeCount: 6,
            grades: mockGradeBuckets.map((grade, index) => ({
              ...grade,
              gradeCount: 1 + index,
            })),
          },
        ],
      }),
    })
  })

  
}
