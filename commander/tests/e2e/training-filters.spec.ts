import { expect, test } from '@playwright/test'
import { installTrainingSessionsFixtures } from '../fixtures/trainingSessions'
import { login } from '../fixtures/mockApi'

test('training lookups send selected IDs; aircraft clears only a mismatched scenario and scrolling stays synchronized', async ({
  page,
}) => {
  await installTrainingSessionsFixtures(page)
  const requests: Record<string, string>[] = []
  page.on('request', (request) => {
    const url = new URL(request.url())
    if (url.pathname === '/api/commander/training-sessions')
      requests.push(Object.fromEntries(url.searchParams))
  })
  await login(page, '/training-sessions')
  await page.getByRole('combobox', { name: 'Scenario', exact: true }).fill('Alpha')
  await page.getByRole('option', { name: /Scenario Alpha/ }).click()
  await page
    .getByRole('combobox', { name: 'Instructor', exact: true })
    .fill('ian.instructor@example.com')
  await page.getByRole('option', { name: /Ian Instructor/ }).click()
  await page.getByRole('combobox', { name: 'Participant', exact: true }).fill('alice.alpha')
  await page.getByRole('option', { name: /Alice Alpha/ }).click()
  await expect
    .poll(() => requests.at(-1))
    .toMatchObject({ scenarioId: '10', instructorId: 'instructor-1', participantId: 'pilot-1' })
  await page.getByRole('combobox', { name: 'Aircraft', exact: true }).selectOption('1')
  await expect.poll(() => requests.at(-1)).toMatchObject({ scenarioId: '10', aircraftId: '1' })
  await page.getByRole('combobox', { name: 'Aircraft', exact: true }).selectOption('2')
  await expect
    .poll(() => requests.at(-1))
    .toMatchObject({
      aircraftId: '2',
      instructorId: 'instructor-1',
      participantId: 'pilot-1',
      offset: '0',
    })
  expect(requests.at(-1)).not.toHaveProperty('scenarioId')
  await expect(page.getByRole('combobox', { name: 'Scenario', exact: true })).toHaveValue('')
  await expect(page.getByRole('combobox', { name: 'Instructor', exact: true })).toHaveValue(
    'Ian Instructor',
  )
  await expect(page.getByRole('combobox', { name: 'Participant', exact: true })).toHaveValue(
    'Alice Alpha',
  )
  await page.setViewportSize({ width: 390, height: 844 })
  const content = page.locator('.sticky-horizontal-scrollbar').first()
  const bottom = page.getByLabel('Scroll training sessions horizontally', { exact: true })
  await expect(bottom).toBeVisible()
  await content.evaluate((element) => (element.scrollLeft = 120))
  await expect.poll(() => bottom.evaluate((element) => element.scrollLeft)).toBe(120)
  await bottom.evaluate((element) => (element.scrollLeft = 50))
  await expect.poll(() => content.evaluate((element) => element.scrollLeft)).toBe(50)
})
