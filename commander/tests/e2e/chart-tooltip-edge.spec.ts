import { expect, test } from '@playwright/test'
import { installAnalyticsFixtures } from '../fixtures/analytics'
import { installMockApi, login } from '../fixtures/mockApi'

test('a tooltip in a horizontally scrolled mobile chart stays inside the viewport and unmounts', async ({
  page,
}) => {
  await installMockApi(page)
  await installAnalyticsFixtures(page)
  await page.setViewportSize({ width: 390, height: 640 })
  await login(page, '/analytics')
  const chart = page.getByRole('img', { name: 'Competency grade distribution chart', exact: true })
  await chart.scrollIntoViewIfNeeded()
  await chart.evaluate((canvas) => {
    const scroller = canvas.closest('.chart-scroll-area')!
    scroller.scrollLeft = scroller.scrollWidth - scroller.clientWidth
  })
  let point: { x: number; y: number } | null = null
  await expect
    .poll(async () => {
      point = await chart.evaluate((node) => {
        const canvas = node as HTMLCanvasElement
        const pixels = canvas.getContext('2d')!.getImageData(0, 0, canvas.width, canvas.height).data
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
        red.sort((a, b) => (b % canvas.width) - (a % canvas.width))
        const pixel = red[Math.floor(red.length * 0.1)]!
        const bounds = canvas.getBoundingClientRect()
        return {
          x: bounds.left + (((pixel % canvas.width) + 0.5) * bounds.width) / canvas.width,
          y:
            bounds.top + ((Math.floor(pixel / canvas.width) + 0.5) * bounds.height) / canvas.height,
        }
      })
      return point
    })
    .not.toBeNull()
  await page.mouse.move(point!.x, point!.y)
  const tooltip = page.locator('[data-chart-external-tooltip]')
  await expect(tooltip).toBeVisible()
  await expect(tooltip).toContainText('CRM')
  await expect(tooltip).toContainText('Below standard: 1')
  await expect(tooltip).toContainText('Standard: 2')
  await expect(tooltip).toContainText('Above standard: 3')
  await expect(tooltip).toContainText('Total: 6')
  const bounds = (await tooltip.boundingBox())!
  expect(bounds.x).toBeGreaterThanOrEqual(0)
  expect(bounds.y).toBeGreaterThanOrEqual(0)
  expect(bounds.x + bounds.width).toBeLessThanOrEqual(390)
  expect(bounds.y + bounds.height).toBeLessThanOrEqual(640)
  await page.getByRole('link', { name: 'Settings', exact: true }).click()
  await expect(tooltip).toHaveCount(0)
})
