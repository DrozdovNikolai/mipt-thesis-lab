import { execFileSync } from 'node:child_process'
import { existsSync } from 'node:fs'
import { join } from 'node:path'
import { expect, test } from '@playwright/test'

test('atomic releases preserve old lazy assets and the session survives rollback to the previous release', async ({
  page,
  request,
}) => {
  const root = process.env.COMMANDER_REHEARSAL_ROOT
  const currentRelease = process.env.COMMANDER_REHEARSAL_CURRENT_RELEASE
  const previousRelease = process.env.COMMANDER_REHEARSAL_PREVIOUS_RELEASE
  test.skip(
    !currentRelease ||
      !previousRelease ||
      !root ||
      !existsSync(join(root, '.commander-disposable-rehearsal')),
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
  activate(currentRelease!)
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
    activate(previousRelease!)
    for (const asset of priorAssets) {
      const response = await request.get(asset)
      expect(response.status()).toBe(200)
      expect(response.headers()['cache-control']).toContain('immutable')
    }
    // The still-open application now lazily imports analytics from the shared asset store.
    await page.getByRole('link', { name: 'Analytics', exact: true }).click()
    await expect(page.locator('canvas')).toHaveCount(4)
    await page.reload()
    // The previous release can read the rotated session from the same origin.
    await expect(page.getByRole('heading', { name: 'Analytics', exact: true })).toBeVisible()
    await expect(page.locator('canvas')).toHaveCount(4)
    await expect(page.getByRole('button', { name: 'Sign in', exact: true })).toHaveCount(0)
    expect(Date.now() - start).toBeLessThan(600_000)
  } finally {
    activate(currentRelease!)
  }
})
