import { expect, test } from '@playwright/test'
import { installProfileFixtures } from '../fixtures/profile'
import { installMockApi, json, login } from '../fixtures/mockApi'
import type {
  CommanderPilotProfile,
  PilotTrainingSummary,
} from '../../src/entities/commander/types'

test('changing the main training type updates the cached profile threshold lines', async ({
  page,
}) => {
  const state = await installMockApi(page)
  await installProfileFixtures(page)
  await page.unroute('**/api/commander/flight-types')
  await page.route('**/api/auth/me', (route) => json(route, state.currentUser))
  await login(page, '/pilots/pilot-1/training-data')
  await expect(page.getByText('Main threshold', { exact: true })).toHaveCount(2)
  await page.getByRole('link', { name: 'Settings', exact: true }).click()
  await page
    .getByRole('button')
    .filter({ has: page.getByRole('heading', { name: 'Upgrade', exact: true }) })
    .click()
  await page.getByRole('button', { name: 'Make main', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Main threshold', exact: true })).toBeDisabled()
  expect(state.flightTypes.filter((type) => type.isMain).map((type) => type.id)).toEqual([2])
  await page.goBack()
  await expect(
    page.getByRole('img', { name: 'Latest pilot competence radar chart', exact: true }),
  ).toBeVisible()
  await expect(page.getByText('Main threshold', { exact: true })).toHaveCount(0)
})

test('pilot ID changes reset selection and scroll; incomplete profile and legacy snapshot stay usable', async ({
  page,
}) => {
  await installMockApi(page)
  await installProfileFixtures(page)
  await page.setViewportSize({ width: 1024, height: 768 })
  const summaryResponse = page.waitForResponse((response) =>
    response.url().endsWith('/pilot-1/training-summary'),
  )
  const profileResponse = page.waitForResponse((response) => response.url().endsWith('/pilot-1'))
  await login(page, '/pilots/pilot-1/training-data')
  const summary = (await (await summaryResponse).json()) as PilotTrainingSummary
  const profile = (await (await profileResponse).json()) as CommanderPilotProfile
  summary.competenceHistories.push({
    competenceId: 2,
    competenceCode: 'PRO',
    competenceName: 'Procedures',
    orderIndex: 2,
    history: [],
  })
  await page.route('**/api/commander/pilots/pilot-1/training-summary', (route) =>
    json(route, summary),
  )
  await page.reload()
  await page.getByRole('button', { name: /^PRO / }).click()
  await expect(
    page.getByRole('img', { name: 'Procedures score history chart', exact: true }),
  ).toBeVisible()
  const next = structuredClone(summary)
  next.pilot.id = 'pilot-2'
  next.pilot.firstName = null
  next.pilot.lastName = null
  next.pilot.fullName = null
  next.pilot.email = 'incomplete@example.test'
  next.pilot.position = null
  next.latestCompletedTraining!.roleProjectionSource = 'LEGACY_PLANNED'
  next.latestCompletedTraining!.title = 'Legacy profile session'
  await page.route('**/api/commander/pilots/pilot-2/training-summary', (route) => json(route, next))
  await page.route('**/api/commander/pilots/pilot-2', (route) =>
    json(route, {
      ...profile,
      id: 'pilot-2',
      firstName: null,
      lastName: null,
      fullName: null,
      position: null,
      phone: null,
      rating: null,
      photoUrl: null,
      email: 'incomplete@example.test',
      aircraftCodes: [],
      aircraftIds: [],
    }),
  )
  await page.locator('main').evaluate((main) => (main.scrollTop = 500))
  await expect
    .poll(() => page.locator('main').evaluate((main) => main.scrollTop))
    .toBeGreaterThan(0)
  // Exercise the browser history event on the mounted router, without a full reload.
  await page.evaluate(() => {
    history.pushState(history.state, '', '/pilots/pilot-2/training-data')
    window.dispatchEvent(new PopStateEvent('popstate', { state: history.state }))
  })
  await expect(
    page.getByRole('heading', { name: 'incomplete@example.test', exact: true }),
  ).toBeVisible()
  await expect(
    page.getByRole('img', { name: 'Communication score history chart', exact: true }),
  ).toBeVisible()
  await expect(
    page.getByRole('img', { name: 'Procedures score history chart', exact: true }),
  ).toHaveCount(0)
  await expect(page.getByText(/Legacy profile session.*Legacy planned roles/)).toBeVisible()
  await expect.poll(() => page.locator('main').evaluate((main) => main.scrollTop)).toBe(0)
  await page.getByRole('link', { name: 'Profile', exact: true }).click()
  await expect(page.getByText('No aircraft assigned to this pilot.', { exact: true })).toBeVisible()
  await expect(page.getByText('Not provided', { exact: true })).toHaveCount(3)
  // Back/Forward use entries produced by real RouterLinks, separately from the injected ID event.
  await page.getByRole('link', { name: 'Training data', exact: true }).click()
  await page.getByRole('link', { name: 'Profile', exact: true }).click()
  await page.goBack()
  await expect(page).toHaveURL(/\/pilot-2\/training-data$/)
  await page.goForward()
  await expect(page).toHaveURL(/\/pilot-2\/profile$/)
  await expect(
    page.getByRole('heading', { name: 'General information', exact: true }),
  ).toBeVisible()
})
