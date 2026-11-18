import { execFileSync } from 'node:child_process'
import { existsSync } from 'node:fs'
import { join } from 'node:path'
import { expect, test } from '@playwright/test'

test('atomic releases preserve old lazy assets and the Vue session survives a React rollback', async ({
  page,
  request,
}) => {
  const root = process.env.COMMANDER_REHEARSAL_ROOT
  const nordRelease = process.env.COMMANDER_REHEARSAL_55NORD_RELEASE || 'vue-55nord-m9'
  const fireflyRelease = process.env.COMMANDER_REHEARSAL_FIREFLY_RELEASE || 'vue-firefly-m9'
  test.skip(
    !root || !existsSync(join(root, '.commander-disposable-rehearsal')),
    'Only the explicitly selected disposable rehearsal root may be switched',
  )
  const activate = (release: string) =>
    execFileSync('python3', [
      'deploy/release.py',
      '--root',
      root!,
      '--release',
      release,
      '--activate',
    ])
  activate(nordRelease)
  try {
    await page.goto('/pilots')
    await expect(page).toHaveTitle('55NORD Commander')
    await expect(page.locator('link[rel="icon"]')).toHaveAttribute('href', '/favicon55nord.ico')
    const nordIcon = await request.get('/favicon55nord.ico')
    expect(nordIcon.status()).toBe(200)
    // The inherited .ico asset contains PNG bytes; preserve the existing public path.
    expect((await nordIcon.body()).subarray(0, 8).toString('hex')).toBe('89504e470d0a1a0a')
    await page.getByRole('textbox', { name: 'Login', exact: true }).fill('admin')
    await page
      .getByRole('textbox', { name: 'Password', exact: true })
      .fill('commander-integration-only')
    await page.getByRole('button', { name: 'Sign in', exact: true }).click()
    await expect(page.getByRole('heading', { name: 'Pilots', exact: true })).toBeVisible()
    await expect(page.getByRole('img', { name: '55NORD Commander', exact: true })).toBeVisible()
    await page.evaluate(() => {
      const envelope = JSON.parse(localStorage.getItem('session-store')!)
      envelope.state.tokens.accessToken = 'force-rehearsal-refresh'
      localStorage.setItem('session-store', JSON.stringify(envelope))
    })
    const refresh = page.waitForResponse((response) => response.url().endsWith('/api/auth/refresh'))
    await page.reload()
    expect((await refresh).status()).toBe(200)
    await expect(page.getByRole('heading', { name: 'Pilots', exact: true })).toBeVisible()
    const priorAssets = await page.evaluate(() =>
      performance
        .getEntriesByType('resource')
        .map((entry) => entry.name)
        .filter((name) => name.includes('/assets/') && name.endsWith('.js')),
    )
    const start = Date.now()
    activate('react-baseline')
    for (const asset of priorAssets) {
      const response = await request.get(asset)
      expect(response.status()).toBe(200)
      expect(response.headers()['cache-control']).toContain('immutable')
    }
    // The still-open Vue shell now lazily imports analytics from the shared asset store.
    await page.getByRole('link', { name: 'Analytics', exact: true }).click()
    await expect(page.locator('canvas')).toHaveCount(4)
    await page.reload()
    // Same origin + unchanged v0 envelope lets React use the rotated Vue token pair.
    await expect(page.getByRole('heading', { name: 'Analytics', exact: true })).toBeVisible()
    await expect(page.locator('canvas')).toHaveCount(4)
    await expect(page.getByRole('button', { name: 'Sign in', exact: true })).toHaveCount(0)
    expect(Date.now() - start).toBeLessThan(600_000)
    activate(fireflyRelease)
    await page.reload()
    await expect(page).toHaveTitle('Firefly Commander')
    await expect(page.locator('html')).toHaveAttribute('data-brand', 'firefly')
    await expect(page.getByRole('heading', { name: 'Analytics', exact: true })).toBeVisible()
    const logo = page.getByRole('img', { name: 'Firefly Commander', exact: true })
    await expect(logo).toBeVisible()
    await expect
      .poll(() => logo.evaluate((node) => (node as HTMLImageElement).naturalWidth))
      .toBeGreaterThan(0)
    await expect(page.locator('link[rel="icon"]')).toHaveAttribute('href', '/favicon.png')
    const fireflyIcon = await request.get('/favicon.png')
    expect(fireflyIcon.status()).toBe(200)
    expect((await fireflyIcon.body()).subarray(0, 8).toString('hex')).toBe('89504e470d0a1a0a')
  } finally {
    activate(nordRelease)
  }
})
