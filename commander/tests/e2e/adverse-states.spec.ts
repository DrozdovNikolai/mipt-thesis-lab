import { expect, test } from '@playwright/test'
import {
  installTrainingSessionsFixtures,
  trainingSessionDetailsById,
} from '../fixtures/trainingSessions'
import { installAnalyticsFixtures } from '../fixtures/analytics'
import { installMockApi, json, login } from '../fixtures/mockApi'
import type { TrainingSessionDetail } from '../../src/entities/commander/types'

for (const backTo of ['https://untrusted.example/elsewhere', { malformed: true }]) {
  test(`invalid back state falls back to training sessions: ${JSON.stringify(backTo)}`, async ({
    page,
  }) => {
    await page.addInitScript(
      (value) => history.replaceState({ ...history.state, backTo: value, backLabel: 42 }, ''),
      backTo,
    )
    await installTrainingSessionsFixtures(page)
    await login(page, '/training-sessions/102')
    await page.getByRole('button', { name: 'Back to training sessions', exact: true }).click()
    await expect(page).toHaveURL(/\/training-sessions$/)
    await expect(
      page.getByRole('heading', { name: 'Training sessions', exact: true }),
    ).toBeVisible()
  })
}

test('analytics lookup caches belong to the newly verified airline session', async ({ page }) => {
  const state = await installMockApi(page)
  await installAnalyticsFixtures(page)
  await page.route('**/api/auth/me', (route) => json(route, state.currentUser))
  const aircraftRequests: string[] = []
  await page.route('**/api/training/aircraft**', (route) => {
    aircraftRequests.push(new URL(route.request().url()).searchParams.get('airlineId') ?? '')
    return json(route, [
      {
        id: state.currentUser.airlineId,
        code: `Airline ${state.currentUser.airlineId} aircraft`,
        name: 'Synthetic aircraft',
        active: true,
        airlineId: state.currentUser.airlineId,
      },
    ])
  })
  await page.route('**/api/users/positions**', (route) =>
    json(route, [
      {
        id: state.currentUser.airlineId,
        name: `Airline ${state.currentUser.airlineId} position`,
        airlineId: state.currentUser.airlineId,
      },
    ]),
  )
  await login(page, '/analytics')
  await expect(page.getByRole('option', { name: 'Airline 1 aircraft', exact: true })).toHaveCount(1)
  await expect(page.getByRole('option', { name: 'Airline 1 position', exact: true })).toHaveCount(1)
  await page.getByRole('button', { name: 'Logout', exact: true }).click()
  state.currentUser = { ...state.currentUser, id: 'airline-2-user', airlineId: 2 }
  await login(page, '/analytics')
  await expect(page.getByRole('option', { name: 'Airline 2 aircraft', exact: true })).toHaveCount(1)
  await expect(page.getByRole('option', { name: 'Airline 2 position', exact: true })).toHaveCount(1)
  await expect(page.getByRole('option', { name: /Airline 1/ })).toHaveCount(0)
  expect(aircraftRequests).toEqual(['1', '2'])
})

for (const variant of ['legacy', 'absent', 'null'] as const) {
  test(`distinguishes ${variant} crew projection`, async ({ page }) => {
    await installTrainingSessionsFixtures(page)
    const detail = structuredClone(
      trainingSessionDetailsById[102],
    ) as unknown as TrainingSessionDetail
    if (variant === 'legacy') {
      delete detail.crewRuntime
      delete detail.participants
    } else if (variant === 'absent') delete detail.crewRuntime!.latestSwap
    else detail.crewRuntime!.latestSwap = null
    await page.route('**/api/commander/training-sessions/102', (route) => json(route, detail))
    await login(page, '/training-sessions/102')
    if (variant === 'legacy')
      await expect(
        page.getByText(
          'Legacy planned roles: this session was completed without a live crew timeline.',
          { exact: true },
        ),
      ).toBeVisible()
    await expect(
      page.getByText(variant === 'null' ? 'No accepted swaps' : 'Latest swap unavailable', {
        exact: true,
      }),
    ).toBeVisible()
    await expect(page.getByText('Before latest swap', { exact: true })).toHaveCount(0)
  })
}

test('another user opening the same training ID cannot see the preceding assessment cache', async ({
  page,
}) => {
  const state = await installMockApi(page)
  await installTrainingSessionsFixtures(page)
  await page.route('**/api/auth/me', (route) => json(route, state.currentUser))
  const detail = structuredClone(
    trainingSessionDetailsById[102],
  ) as unknown as TrainingSessionDetail
  detail.assessments[0]!.pilotFirstName = 'Private'
  detail.assessments[0]!.pilotLastName = 'Assessment A'
  await page.route('**/api/commander/training-sessions/102', (route) => json(route, detail))
  await login(page, '/training-sessions/102')
  await expect(
    page.getByRole('heading', { name: 'Private Assessment A', exact: true }),
  ).toBeVisible()
  await page.getByRole('button', { name: 'Logout', exact: true }).click()
  await expect(
    page.getByRole('heading', { name: 'Private Assessment A', exact: true }),
  ).toHaveCount(0)
  state.currentUser = { ...state.currentUser, id: 'user-B', airlineId: 2 }
  detail.assessments[0]!.pilotFirstName = 'Private'
  detail.assessments[0]!.pilotLastName = 'Assessment B'
  await login(page, '/training-sessions/102')
  await expect(
    page.getByRole('heading', { name: 'Private Assessment B', exact: true }),
  ).toBeVisible()
  await expect(
    page.getByRole('heading', { name: 'Private Assessment A', exact: true }),
  ).toHaveCount(0)
})

test('keeps assessment-specific AI review and PDF IDs; failed PDF closes its pre-opened popup', async ({
  page,
}) => {
  await installTrainingSessionsFixtures(page)
  await login(page, '/training-sessions/102')
  await page.getByRole('button', { name: 'AI review', exact: true }).click()
  await expect(
    page.getByText('AI review for communication competence', { exact: true }),
  ).toBeVisible()
  await page.getByRole('button', { name: /Participant · current CM1/ }).click()
  await expect(
    page.getByText('No AI review content is available for this assessment.', { exact: true }),
  ).toBeVisible()
  let requestPath = '',
    popupAlreadyOpen = false
  await page.route('**/report.pdf', async (route) => {
    requestPath = new URL(route.request().url()).pathname
    popupAlreadyOpen = page.context().pages().length > 1
    await json(route, { detail: 'Synthetic report unavailable' }, 503)
  })
  const popupPromise = page.waitForEvent('popup')
  await page.getByRole('button', { name: 'Export PDF', exact: true }).click()
  const popup = await popupPromise
  await expect(page.getByRole('alert')).toHaveText('Synthetic report unavailable')
  expect(requestPath).toBe('/api/commander/training-sessions/102/assessments/902/report.pdf')
  expect(popupAlreadyOpen).toBe(true)
  await expect.poll(() => popup.isClosed()).toBe(true)
  await expect(page.getByRole('button', { name: 'Export PDF', exact: true })).toBeEnabled()
})

test('changing only training day resets the selected assessment and tab; Back restores the route', async ({
  page,
}) => {
  await installTrainingSessionsFixtures(page)
  const first = structuredClone(trainingSessionDetailsById[102]) as unknown as TrainingSessionDetail
  first.session.previousDays = [{ id: 103, title: 'Earlier day', dayIndex: 0 }]
  const second = structuredClone(first)
  second.session.id = 103
  second.session.title = 'Earlier day'
  second.session.previousDays = []
  second.assessments[0]!.pilotFirstName = 'Different'
  second.assessments[0]!.pilotLastName = 'Pilot'
  await page.route('**/api/commander/training-sessions/102', (route) => json(route, first))
  await page.route('**/api/commander/training-sessions/103', (route) => json(route, second))
  await login(page, '/training-sessions/102')
  await page.getByRole('button', { name: /Participant · current CM1/ }).click()
  await page.getByRole('button', { name: 'AI review', exact: true }).click()
  await page.getByRole('link', { name: 'Day 0', exact: true }).click()
  await expect(page).toHaveURL(/\/training-sessions\/103$/)
  await expect(page.getByRole('heading', { name: 'Different Pilot', exact: true })).toBeVisible()
  await expect(
    page.getByRole('heading', { name: 'Comments and attempts', exact: true }),
  ).toBeVisible()
  await page.getByRole('button', { name: 'Back to training session', exact: true }).click()
  await expect(page).toHaveURL(/\/training-sessions\/102$/)
})

test('analytics applies the same valid filters to four endpoints and isolates a failed card', async ({
  page,
}) => {
  await installAnalyticsFixtures(page)
  await page.route('**/api/commander/analytics/competencies/average-trend**', (route) =>
    json(route, { items: [], pilotsWithCompletedTraining: 0 }),
  )
  const calls: URL[] = []
  page.on('request', (request) => {
    if (request.url().includes('/api/commander/analytics/')) calls.push(new URL(request.url()))
  })
  await login(page, '/analytics')
  await page.getByLabel('Age to', { exact: true }).fill('50')
  await page.getByLabel('Age from', { exact: true }).fill('30')
  await page.getByRole('combobox', { name: 'Aircraft', exact: true }).selectOption('1')
  await page.getByLabel('As of date', { exact: true }).fill('2026-01-01')
  await expect
    .poll(
      () =>
        new Set(
          calls
            .filter(
              (url) =>
                url.searchParams.get('asOfDate') === '2026-01-01' &&
                url.searchParams.get('ageFromYears') === '30' &&
                url.searchParams.get('ageToYears') === '50' &&
                url.searchParams.get('aircraftId') === '1',
            )
            .map((url) => url.pathname),
        ).size,
    )
    .toBe(4)
  await page.getByLabel('Age from', { exact: true }).fill('60')
  await expect(page.getByText(/Age from must be less than/)).toBeVisible()
  await page.route('**/api/commander/analytics/instructors/grade-distribution**', (route) =>
    json(route, { detail: 'Instructor service unavailable' }, 503),
  )
  // Another valid filter forces a request while the invalid age remains held.
  await page.getByLabel('As of date', { exact: true }).fill('2026-02-01')
  await expect(page.getByText('Instructor service unavailable', { exact: true })).toBeVisible()
  expect(calls.some((url) => url.searchParams.get('ageFromYears') === '60')).toBe(false)
  await expect(
    page.getByRole('img', { name: 'Competency grade distribution chart', exact: true }),
  ).toBeVisible()
  await expect(
    page.getByRole('img', { name: 'Pilot grade distribution chart', exact: true }),
  ).toBeVisible()
})

test('changes trend competence and local ranking without fetching analytics again', async ({
  page,
}) => {
  await installAnalyticsFixtures(page)
  const calls: string[] = []
  page.on('request', (request) => {
    if (request.url().includes('/api/commander/analytics/')) calls.push(request.url())
  })
  await page.route('**/api/commander/analytics/competencies/average-trend**', (route) =>
    json(route, {
      totalPilots: 6,
      pilotsWithCompletedTraining: 6,
      filters: {},
      items: [
        {
          competenceId: 1,
          competenceCode: 'OPS',
          competenceName: 'Operations',
          orderIndex: 1,
          points: [
            {
              periodStart: '2026-01-01',
              periodEnd: '2026-06-30',
              periodLabel: 'H1 2026',
              averageScoreNumeric: '3.5',
              pilotCount: 6,
            },
          ],
        },
        {
          competenceId: 2,
          competenceCode: 'CRM',
          competenceName: 'Crew Resource Management',
          orderIndex: 2,
          points: [],
        },
      ],
    }),
  )
  await login(page, '/analytics')
  await expect(page.locator('canvas')).toHaveCount(4)
  await expect.poll(() => calls.length).toBe(4)
  const initialCalls = [...calls]
  await page.getByRole('combobox', { name: 'Competency', exact: true }).selectOption('2')
  await expect(
    page.getByText('No competency trend is available for the selected filters.', { exact: true }),
  ).toBeVisible()
  await page.getByRole('combobox', { name: 'Competency', exact: true }).selectOption('1')
  await expect(
    page.getByRole('img', { name: 'Competency half-year average trend chart', exact: true }),
  ).toBeVisible()
  await page.getByLabel('Top performers', { exact: true }).fill('1')
  await page.getByLabel('Training concern', { exact: true }).fill('1')
  await expect(page.getByText('2 of 3 pilots', { exact: true })).toBeVisible()
  expect(calls).toEqual(initialCalls)
})

for (const status of [403, 404, 503]) {
  test(`training detail ${status} retains a usable return action`, async ({ page }) => {
    await installMockApi(page)
    await page.route('**/api/commander/training-sessions/999', (route) =>
      json(route, { detail: `Detail error ${status}` }, status),
    )
    await login(page, '/training-sessions/999')
    await expect(page.getByRole('alert')).toHaveText(`Detail error ${status}`)
    await page.getByRole('button', { name: 'Back to training sessions', exact: true }).click()
    await expect(page).toHaveURL(/\/training-sessions$/)
  })
}
