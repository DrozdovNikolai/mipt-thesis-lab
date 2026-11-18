import { mkdirSync, writeFileSync } from 'node:fs'
import { gzipSync } from 'node:zlib'
import { expect, test } from '@playwright/test'
import { installAnalyticsFixtures } from '../fixtures/analytics'
import { installPilotsFixtures } from '../fixtures/pilots'

test('measures pilots and analytics in cold browser contexts', async ({ browser }) => {
  const samples: {
    route: string
    readyMs: number
    harnessReadyMs: number
    domContentLoadedMs: number
    loadMs: number
    requests: number
    javascriptGzipBytes: number
    javascriptFiles: string[]
  }[] = []
  for (let repeat = 0; repeat < 5; repeat++) {
    for (const route of ['pilots', 'analytics']) {
      const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
      const page = await context.newPage()
      await (route === 'pilots' ? installPilotsFixtures : installAnalyticsFixtures)(page)
      await page.setViewportSize({ width: 1440, height: 1000 })
      await page.addInitScript(() =>
        localStorage.setItem(
          'session-store',
          JSON.stringify({
            version: 0,
            state: {
              tokens: { accessToken: 'test-access-token', refreshToken: 'test-refresh-token' },
              user: null,
              privileges: [],
            },
          }),
        ),
      )
      await page.addInitScript((routeName) => {
        const isReady = () =>
          routeName === 'pilots'
            ? Boolean(
                document.querySelector(
                  '[role="link"][aria-label="Open Alpha, Alice profile in a new tab"]',
                ),
              )
            : document.querySelectorAll('canvas').length === 4
        const observer = new MutationObserver(() => {
          if (!isReady()) return
          observer.disconnect()
          // Measure in the page so Playwright assertion polling cannot add latency.
          requestAnimationFrame(() =>
            requestAnimationFrame(() => performance.mark('commander-ready')),
          )
        })
        observer.observe(document, { childList: true, subtree: true, attributes: true })
      }, route)
      let requests = 0
      page.on('request', (request) => {
        if (request.url().includes('/api/')) requests++
      })
      const start = performance.now()
      await page.goto(`http://127.0.0.1:4177/${route}`)
      if (route === 'pilots')
        await expect(
          page.getByRole('link', { name: 'Open Alpha, Alice profile in a new tab', exact: true }),
        ).toBeVisible()
      else await expect(page.locator('canvas')).toHaveCount(4)
      await page.waitForFunction(() => performance.getEntriesByName('commander-ready').length)
      const harnessReadyMs = performance.now() - start
      const timing = await page.evaluate(() => {
        const navigation = performance.getEntriesByType(
          'navigation',
        )[0] as PerformanceNavigationTiming
        return {
          readyMs: performance.getEntriesByName('commander-ready')[0]!.startTime,
          domContentLoadedMs: navigation.domContentLoadedEventEnd,
          loadMs: navigation.loadEventEnd,
        }
      })
      const javascriptFiles = await page.evaluate(() =>
        performance
          .getEntriesByType('resource')
          .map((entry) => entry.name)
          .filter((name) => /\/assets\/.*\.js$/.test(name)),
      )
      let javascriptGzipBytes = 0
      for (const asset of javascriptFiles)
        javascriptGzipBytes += gzipSync(await (await context.request.get(asset)).body()).byteLength
      if (route === 'pilots')
        expect(javascriptFiles.some((name) => /Chart|AnalyticsView/.test(name))).toBe(false)
      samples.push({
        route,
        readyMs: Math.round(timing.readyMs),
        harnessReadyMs: Math.round(harnessReadyMs),
        domContentLoadedMs: Math.round(timing.domContentLoadedMs),
        loadMs: Math.round(timing.loadMs),
        requests,
        javascriptGzipBytes,
        javascriptFiles: javascriptFiles.map((name) => new URL(name).pathname),
      })
      await context.close()
    }
  }
  const median = (values: number[]) =>
    [...values].sort((a, b) => a - b)[Math.floor(values.length / 2)]!
  const summary = ['pilots', 'analytics'].map((route) => {
    const items = samples.filter((item) => item.route === route)
    return {
      route,
      medianReadyMs: median(items.map((item) => item.readyMs)),
      medianApiRequests: median(items.map((item) => item.requests)),
      medianJavascriptGzipBytes: median(items.map((item) => item.javascriptGzipBytes)),
    }
  })
  mkdirSync('test-results/performance', { recursive: true })
  writeFileSync(
    'test-results/performance/performance.json',
    JSON.stringify(
      {
        browser: browser.version(),
        repeats: 5,
        method:
          'Fresh browser context per sample, no network throttling, /me revalidation. Browser timing starts at navigation and records two paint frames after the loaded row or four canvas nodes appear. Gzip computed identically with Node zlib.',
        timingMethod:
          'readyMs is a browser Performance mark from navigation start, recorded by a pre-navigation MutationObserver two animation frames after the loaded row/four canvases appear. Assertions independently verify readiness; the page.goto load wait and assertion polling are excluded from readyMs. harnessReadyMs records the outer Playwright wait for diagnosis. This is not a full chart-animation measurement.',
        summary,
        samples,
      },
      null,
      2,
    ) + '\n',
  )
})
