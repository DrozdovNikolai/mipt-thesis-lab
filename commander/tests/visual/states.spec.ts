import { mkdirSync } from 'node:fs'
import { expect, test } from '@playwright/test'
import { screens } from '../fixtures/visualScreens'
import { visualStatePage } from '../fixtures/visualStates'

for (const width of [390, 768, 1024, 1440]) {
  for (const state of ['loading', 'empty', 'error'] as const) {
    for (const screen of screens) {
      test(`${screen.name} ${state} ${width}`, async ({ page }) => {
        const errors: string[] = []
        page.on('pageerror', (error) => errors.push(error.message))
        await page.route('**/api/**', (route) =>
          route.fulfill({
            status: 404,
            contentType: 'application/json',
            body: '{"detail":"Unconfigured fixture"}',
          }),
        )
        const modified = visualStatePage(page, state)
        await screen.fixture(modified.page)
        await page.setViewportSize({ width, height: 1000 })
        try {
          await page.goto(`${screen.path}`)
          await page.getByRole('textbox', { name: 'Login', exact: true }).fill('commander')
          await page.getByRole('textbox', { name: 'Password', exact: true }).fill('fixture-only')
          await page.getByRole('button', { name: 'Sign in', exact: true }).click()
          await expect(page.getByRole('main')).toBeVisible()
          if (state !== 'loading') await page.waitForLoadState('networkidle')
          if (state === 'error')
            await expect(
              page.getByText('Visual fixture unavailable', { exact: false }).first(),
            ).toBeVisible()
          // Two paint frames capture the pending DOM without releasing API responses.
          await page.evaluate(
            () =>
              new Promise<void>((resolve) =>
                requestAnimationFrame(() => requestAnimationFrame(() => resolve())),
              ),
          )
          const directory = `test-results/screenshots/states`
          mkdirSync(directory, { recursive: true })
          await page.screenshot({
            path: `${directory}/${screen.name}-${state}-${width}.png`,
            fullPage: true,
            animations: 'disabled',
          })
          expect(errors).toEqual([])
          expect(
            await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1),
          ).toBe(true)
        } finally {
          modified.release()
        }
      })
    }
  }
}
