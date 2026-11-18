import { mkdirSync } from 'node:fs'
import { expect, test } from '@playwright/test'
import { screens } from '../fixtures/visualScreens'

for (const width of [390, 768, 1024, 1440, 1920]) {
  for (const screen of screens) {
    test(`${screen.name} ${width}`, async ({ page }) => {
      const errors: string[] = []
      page.on('pageerror', (error) => errors.push(error.message))
      // Baseline tests intentionally omit unrelated endpoints. Keep them isolated.
      await page.route('**/api/**', (route) =>
        route.fulfill({
          status: 404,
          contentType: 'application/json',
          body: '{"detail":"Unconfigured fixture"}',
        }),
      )
      await screen.fixture(page)
      await page.setViewportSize({ width, height: 1000 })
      await page.goto(`${screen.path}`)
      await page.getByRole('textbox', { name: 'Login', exact: true }).fill('commander')
      await page.getByRole('textbox', { name: 'Password', exact: true }).fill('fixture-only')
      await page.getByRole('button', { name: 'Sign in', exact: true }).click()
      await expect(
        page.getByRole('heading', { name: screen.ready, exact: true }).first(),
      ).toBeVisible()
      await page.waitForLoadState('networkidle')
      const directory = `test-results/screenshots`
      mkdirSync(directory, { recursive: true })
      await page.screenshot({
        path: `${directory}/${screen.name}-${width}.png`,
        fullPage: true,
        animations: 'disabled',
      })
      expect(errors).toEqual([])
      expect(
        await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1),
      ).toBe(true)
    })
  }
}
