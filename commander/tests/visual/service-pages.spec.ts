import { mkdirSync } from 'node:fs'
import { expect, test } from '@playwright/test'
import { installMockApi } from '../fixtures/mockApi'

for (const implementation of ['react', 'vue']) {
  for (const width of [390, 768, 1024, 1440]) {
    for (const screen of ['login', 'admin', 'forbidden']) {
      test(`${implementation} service ${screen} ${width}`, async ({ page }) => {
        await installMockApi(page, screen === 'forbidden' ? [] : ['pilots:read', 'users:read'])
        await page.setViewportSize({ width, height: 1000 })
        await page.goto(
          `http://127.0.0.1:${implementation === 'react' ? 4176 : 4177}/${screen === 'login' ? 'pilots' : 'admin'}`,
        )
        if (screen === 'login') {
          await expect(page.getByRole('button', { name: 'Sign in', exact: true })).toBeVisible()
        } else {
          await page.getByRole('textbox', { name: 'Login', exact: true }).fill('commander')
          await page.getByRole('textbox', { name: 'Password', exact: true }).fill('fixture-only')
          await page.getByRole('button', { name: 'Sign in', exact: true }).click()
          if (screen === 'admin')
            await expect(page.getByRole('heading', { name: 'Admin', exact: true })).toBeVisible()
          else await expect(page).toHaveURL(/\/forbidden$/)
        }
        await page.waitForLoadState('networkidle')
        const directory = `migration/evidence/${implementation === 'react' ? 'm0/react' : 'm9/vue'}/service`
        mkdirSync(directory, { recursive: true })
        await page.screenshot({
          path: `${directory}/${screen}-${width}.png`,
          fullPage: true,
          animations: 'disabled',
        })
        expect(
          await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1),
        ).toBe(true)
      })
    }
  }
}
