import { expect, test } from '@playwright/test'

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

test('keeps filters on the right and lower distribution cards on one row at 1024px', async ({ page }) => {
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

  await page.goto('/')
  await page.getByRole('textbox', { name: 'Login' }).fill('admin')
  await page.getByRole('textbox', { name: 'Password' }).fill('admin123')
  await page.getByRole('button', { name: 'Sign in' }).click()
  await page.getByRole('link', { name: 'Analytics' }).click()

  const competencyCard = page
    .getByRole('heading', { name: 'Competency Overview' })
    .locator('xpath=ancestor::section[1]')
  const pilotCard = page.getByRole('heading', { name: 'Pilot Performance' }).locator('xpath=ancestor::section[1]')
  const trendCard = page.getByRole('heading', { name: 'Line chart' }).locator('xpath=ancestor::section[1]')
  const instructorCard = page
    .getByRole('heading', { name: 'Instructor Assessment' })
    .locator('xpath=ancestor::section[1]')
  const filtersCard = page.getByRole('button', { name: 'Reset filters' }).locator('xpath=ancestor::aside[1]')
  const aircraftSelect = page.getByRole('combobox', { name: 'Aircraft' })
  const asOfDateInput = page.getByRole('textbox', { name: 'As of date' })
  const resetButton = page.getByRole('button', { name: 'Reset filters' })

  await expect(competencyCard).toBeVisible()
  await expect(pilotCard).toBeVisible()
  await expect(trendCard).toBeVisible()
  await expect(instructorCard).toBeVisible()
  await expect(filtersCard).toBeVisible()
  await expect(aircraftSelect).toBeVisible()
  await expect(asOfDateInput).toBeVisible()
  await expect(resetButton).toBeVisible()
  await expect(aircraftSelect.locator('option')).toHaveText(['All aircraft', 'B737'])

  const filtersTopBeforeScroll = await filtersCard.evaluate((node) => node.getBoundingClientRect().top)
  const competencyBox = await competencyCard.boundingBox()
  const pilotBox = await pilotCard.boundingBox()
  const trendBox = await trendCard.boundingBox()
  const instructorBox = await instructorCard.boundingBox()
  const filtersBox = await filtersCard.boundingBox()
  const aircraftBox = await aircraftSelect.boundingBox()
  const asOfDateBox = await asOfDateInput.boundingBox()
  const resetButtonBox = await resetButton.boundingBox()

  expect(competencyBox).not.toBeNull()
  expect(pilotBox).not.toBeNull()
  expect(trendBox).not.toBeNull()
  expect(instructorBox).not.toBeNull()
  expect(filtersBox).not.toBeNull()
  expect(aircraftBox).not.toBeNull()
  expect(asOfDateBox).not.toBeNull()
  expect(resetButtonBox).not.toBeNull()
  expect(Math.abs((competencyBox?.y ?? 0) - (filtersBox?.y ?? 0))).toBeLessThan(8)
  expect((filtersBox?.x ?? 0) - (competencyBox?.x ?? 0)).toBeGreaterThan(280)
  expect(Math.abs((pilotBox?.y ?? 0) - (competencyBox?.y ?? 0))).toBeLessThan(8)
  expect((pilotBox?.x ?? 0) - (competencyBox?.x ?? 0)).toBeGreaterThan(40)
  expect((trendBox?.y ?? 0) - (competencyBox?.y ?? 0)).toBeGreaterThan(180)
  expect(Math.abs((trendBox?.y ?? 0) - (instructorBox?.y ?? 0))).toBeLessThan(8)
  expect((instructorBox?.x ?? 0) - (trendBox?.x ?? 0)).toBeGreaterThan(40)
  expect((aircraftBox?.x ?? 0) + (aircraftBox?.width ?? 0)).toBeLessThanOrEqual((filtersBox?.x ?? 0) + (filtersBox?.width ?? 0) - 12)
  expect((asOfDateBox?.x ?? 0) + (asOfDateBox?.width ?? 0)).toBeLessThanOrEqual((filtersBox?.x ?? 0) + (filtersBox?.width ?? 0) - 12)
  expect((resetButtonBox?.x ?? 0) + (resetButtonBox?.width ?? 0)).toBeLessThanOrEqual((filtersBox?.x ?? 0) + (filtersBox?.width ?? 0) - 12)
  expect((aircraftBox?.x ?? 0)).toBeGreaterThanOrEqual((filtersBox?.x ?? 0) + 12)
  expect((asOfDateBox?.x ?? 0)).toBeGreaterThanOrEqual((filtersBox?.x ?? 0) + 12)
  expect((resetButtonBox?.x ?? 0)).toBeGreaterThanOrEqual((filtersBox?.x ?? 0) + 12)

  const scrollArea = page.locator('main.app-shell-scroll-area')
  await scrollArea.evaluate((node) => node.scrollTo({ top: 500, behavior: 'instant' }))
  const filtersTopAfterScroll = await filtersCard.evaluate((node) => node.getBoundingClientRect().top)
  const scrollAreaTop = await scrollArea.evaluate((node) => node.getBoundingClientRect().top)

  expect(await scrollArea.evaluate((node) => node.scrollTop)).toBeGreaterThan(20)
  expect(filtersTopAfterScroll).toBeLessThanOrEqual(filtersTopBeforeScroll + 1)
  expect(filtersTopAfterScroll).toBeGreaterThanOrEqual(scrollAreaTop)
  expect(filtersTopAfterScroll).toBeLessThan(scrollAreaTop + 16)
})
