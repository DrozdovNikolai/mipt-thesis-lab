import { expect, test } from '@playwright/test'
import { installAnalyticsFixtures } from '../fixtures/analytics'
import { installMockApi, login } from '../fixtures/mockApi'

declare global {
  interface Window {
    commanderObservedTargets?: Map<ResizeObserver, Set<Element>>
  }
}

test('chart routes dispose tooltips over twenty transitions and filters remain usable at 200% layout scale', async ({
  page,
}) => {
  await page.addInitScript(() => {
    const Original = window.ResizeObserver
    const targets = new Map<ResizeObserver, Set<Element>>()
    window.commanderObservedTargets = targets
    window.ResizeObserver = class extends Original {
      override observe(target: Element, options?: ResizeObserverOptions) {
        if (!targets.has(this)) targets.set(this, new Set())
        targets.get(this)!.add(target)
        super.observe(target, options)
      }
      override unobserve(target: Element) {
        targets.get(this)?.delete(target)
        super.unobserve(target)
      }
      override disconnect() {
        targets.delete(this)
        super.disconnect()
      }
    }
  })
  await installMockApi(page)
  await installAnalyticsFixtures(page)
  await page.setViewportSize({ width: 1024, height: 900 })
  await login(page, '/analytics')
  for (let index = 0; index < 20; index++) {
    await expect(page.locator('canvas')).toHaveCount(4)
    const chart = page.getByRole('img', {
      name: 'Competency grade distribution chart',
      exact: true,
    })
    let point: { x: number; y: number } | null = null
    await expect
      .poll(async () => {
        point = await chart.evaluate((element) => {
          const canvas = element as HTMLCanvasElement
          const pixels = canvas
            .getContext('2d')!
            .getImageData(0, 0, canvas.width, canvas.height).data
          const red: number[] = []
          for (let offset = 0; offset < pixels.length; offset += 4) {
            if (
              pixels[offset]! > 160 &&
              pixels[offset + 1]! < 110 &&
              pixels[offset + 2]! < 110 &&
              pixels[offset + 3]! > 220
            )
              red.push(offset / 4)
          }
          if (!red.length) return null
          const pixel = red[Math.floor(red.length / 2)]!
          const bounds = canvas.getBoundingClientRect()
          return {
            x: (((pixel % canvas.width) + 0.5) * bounds.width) / canvas.width,
            y: ((Math.floor(pixel / canvas.width) + 0.5) * bounds.height) / canvas.height,
          }
        })
        return point
      })
      .not.toBeNull()
    await chart.hover({ position: point! })
    await expect(page.locator('[data-chart-external-tooltip]')).toHaveCount(1)
    const tooltip = page.locator('[data-chart-external-tooltip]')
    await expect(tooltip).toBeVisible()
    const tip = (await tooltip.boundingBox())!
    expect(tip.x).toBeGreaterThanOrEqual(0)
    expect(tip.x + tip.width).toBeLessThanOrEqual(1024)
    await page.getByRole('link', { name: 'Settings', exact: true }).click()
    await expect(page.locator('canvas')).toHaveCount(0)
    await expect(page.locator('[data-chart-external-tooltip]')).toHaveCount(0)
    expect(
      await page.evaluate(
        () =>
          [...window.commanderObservedTargets!.values()]
            .flatMap((set) => [...set])
            .filter((element) => !element.isConnected).length,
      ),
    ).toBe(0)
    await page.getByRole('link', { name: 'Analytics', exact: true }).click()
  }
  // 1024 CSS px at 200% browser zoom has the same layout width as 512 CSS px.
  await page.setViewportSize({ width: 512, height: 450 })
  await page.getByRole('spinbutton', { name: 'Top performers', exact: true }).fill('1')
  await page.getByRole('spinbutton', { name: 'Variance min', exact: true }).fill('0.2')
  await expect(page.getByRole('spinbutton', { name: 'Variance min', exact: true })).toHaveValue(
    '0.2',
  )
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(
    true,
  )
  // Native label and input boxes must not overlap even inside narrow desktop cards.
  await page.setViewportSize({ width: 1024, height: 900 })
  const overlaps = await page.locator('label:has(input[type="number"])').evaluateAll(
    (labels) =>
      labels.filter((label) => {
        const caption = label.querySelector('span')?.getBoundingClientRect()
        const input = label.querySelector('input')?.getBoundingClientRect()
        return (
          caption &&
          input &&
          caption.right > input.left + 1 &&
          caption.top < input.bottom &&
          input.top < caption.bottom
        )
      }).length,
  )
  expect(overlaps).toBe(0)
})

test('switching users removes unsaved settings drafts and protected navigation', async ({
  page,
}) => {
  const state = await installMockApi(page)
  await login(page, '/settings')
  await page.getByLabel('Training type name', { exact: true }).fill('Private draft from user A')
  await page.getByRole('button', { name: 'Logout', exact: true }).click()
  state.currentUser = { ...state.currentUser, id: 'other', login: 'other', privileges: [] }
  await page.getByRole('textbox', { name: 'Login', exact: true }).fill('other')
  await page.getByRole('textbox', { name: 'Password', exact: true }).fill('fixture-only')
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await expect(page).toHaveURL(/\/forbidden$/)
  await expect(page.getByRole('link', { name: 'Settings', exact: true })).toHaveCount(0)
  await page.getByRole('button', { name: 'Logout', exact: true }).click()
  state.currentUser.privileges = ['pilots:read', 'pilots:write']
  await page.goto('/settings')
  await page.getByRole('textbox', { name: 'Login', exact: true }).fill('other')
  await page.getByRole('textbox', { name: 'Password', exact: true }).fill('fixture-only')
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await expect(page.getByLabel('Training type name', { exact: true })).toHaveValue('Recurrent')
})
