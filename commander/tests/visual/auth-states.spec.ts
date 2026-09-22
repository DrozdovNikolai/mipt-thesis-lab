import { mkdirSync } from 'node:fs'
import { expect, test } from '@playwright/test'
import { installMockApi, json, tokenPair } from '../fixtures/mockApi'

for (const width of [390, 768, 1024, 1440]) {
  for (const state of ['login-pending', 'login-error', 'bootstrap-pending', 'bootstrap-error']) {
    test(`auth ${state} ${width}`, async ({ page }) => {
      const api = await installMockApi(page)
      const bootstrap = state.startsWith('bootstrap')
      const pending = state.endsWith('pending')
      let requested = false
      let finish: (() => Promise<void>) | undefined
      await page.route(`**/api/auth/${bootstrap ? 'me' : 'login'}`, (route) => {
        requested = true
        if (pending) {
          finish = () => json(route, bootstrap ? api.currentUser : tokenPair)
          return
        }
        return json(route, { detail: 'Visual authentication failure' }, bootstrap ? 503 : 401)
      })
      if (bootstrap) {
        await page.addInitScript((tokens) => {
          localStorage.setItem(
            'session-store',
            JSON.stringify({ state: { tokens, user: null, privileges: [] }, version: 0 }),
          )
        }, tokenPair)
      }
      await page.setViewportSize({ width, height: 1000 })
      await page.goto(`/settings`)
      if (!bootstrap) {
        await page.getByLabel('Login', { exact: true }).fill('commander')
        await page.getByLabel('Password', { exact: true }).fill('fixture-only')
        await page.getByRole('button', { name: 'Sign in', exact: true }).click()
      }
      await expect.poll(() => requested).toBe(true)
      if (bootstrap) {
        if (pending) {
          await expect(page.getByText('loading', { exact: true })).toBeVisible()
        } else {
          await expect(
            page.getByRole('heading', { name: 'Session check failed', exact: true }),
          ).toBeVisible()
        }
      } else if (pending) {
        await expect(page.getByRole('button', { name: 'Sign in...', exact: true })).toBeDisabled()
      } else {
        await expect(page.getByRole('alert')).toContainText('Visual authentication failure')
      }
      const directory = `test-results/screenshots/auth`
      mkdirSync(directory, { recursive: true })
      await page.screenshot({
        path: `${directory}/${state}-${width}.png`,
        fullPage: true,
        animations: 'disabled',
      })
      expect(
        await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1),
      ).toBe(true)
      if (finish) await finish()
    })
  }
}
