import { mkdirSync } from 'node:fs'
import { expect, test, type Locator } from '@playwright/test'
import { installAnalyticsFixtures } from '../fixtures/analytics'
import { json } from '../fixtures/mockApi'

async function waitForCanvas(chart: Locator) {
  let previous = '',
    stable = 0
  await expect
    .poll(
      async () => {
        const pixels = await chart.evaluate((node) => (node as HTMLCanvasElement).toDataURL())
        stable = pixels === previous ? stable + 1 : 0
        previous = pixels
        return stable
      },
      { intervals: [100], timeout: 5000 },
    )
    .toBeGreaterThanOrEqual(3)
}

test(`ranked separator and single-point trend with long label`, async ({ page }) => {
  await installAnalyticsFixtures(page)
  await page.route('**/api/commander/analytics/competencies/average-trend**', (route) =>
    json(route, {
      totalPilots: 1,
      pilotsWithCompletedTraining: 1,
      filters: {},
      items: [
        {
          competenceId: 1,
          competenceCode: 'LONG',
          competenceName:
            'Operational communication and shared situational awareness during abnormal flight conditions',
          orderIndex: 1,
          points: [
            {
              periodStart: '2026-01-01',
              periodEnd: '2026-06-30',
              periodLabel: 'First half of the 2026 reporting period',
              averageScoreNumeric: '3.5',
              pilotCount: 1,
            },
          ],
        },
      ],
    }),
  )
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  await page.goto(`/analytics`)
  await page.getByLabel('Login', { exact: true }).fill('commander')
  await page.getByLabel('Password', { exact: true }).fill('fixture-only')
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await expect(page.locator('canvas')).toHaveCount(4)
  await page.getByRole('spinbutton', { name: 'Top performers', exact: true }).fill('1')
  await page.getByRole('spinbutton', { name: 'Training concern', exact: true }).fill('1')
  await expect(page.getByText('2 of 3 pilots', { exact: true })).toBeVisible()
  const directory = `test-results/screenshots/charts`
  mkdirSync(directory, { recursive: true })
  const ranked = page.getByRole('img', { name: 'Pilot grade distribution chart', exact: true })
  await waitForCanvas(ranked)
  await ranked.screenshot({ path: `${directory}/ranked-separator.png`, animations: 'disabled' })
  const trend = page.getByRole('img', {
    name: 'Competency half-year average trend chart',
    exact: true,
  })
  await trend.scrollIntoViewIfNeeded()
  await waitForCanvas(trend)
  await trend.screenshot({
    path: `${directory}/single-point-long-label.png`,
    animations: 'disabled',
  })
  for (const width of [390, 1440]) {
    await page.setViewportSize({ width, height: 900 })
    await expect
      .poll(() => trend.evaluate((node) => (node as HTMLCanvasElement).width))
      .toBeGreaterThan(0)
  }
  expect(errors).toEqual([])
})
