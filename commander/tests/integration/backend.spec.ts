import { readFileSync } from 'node:fs'
import { expect, test, type Page } from '@playwright/test'

const fixture = JSON.parse(
  readFileSync(new URL('../fixtures/backend-fixture.json', import.meta.url), 'utf8'),
) as {
  firstPilotId: string
  secondPilotId: string
  training_id: number
  flightTypeId: number
}
async function signIn(page: Page, path: string) {
  await page.goto(path)
  await page.getByRole('textbox', { name: 'Login', exact: true }).fill('admin')
  await page
    .getByRole('textbox', { name: 'Password', exact: true })
    .fill('commander-integration-only')
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await expect(page.getByRole('link', { name: 'Pilots', exact: true })).toBeVisible()
}

test('real API: protected avatar loads as a Blob and is released on logout', async ({
  page,
  request,
}) => {
  await signIn(page, '/pilots')
  // Generate a synthetic image in the browser; upload only to the isolated fixture pilot.
  const uploaded = await page.evaluate(async (pilotId) => {
    const canvas = document.createElement('canvas')
    canvas.width = canvas.height = 8
    const context = canvas.getContext('2d')!
    context.fillStyle = '#257bb4'
    context.fillRect(0, 0, 8, 8)
    const blob = await new Promise<Blob>((resolve) => canvas.toBlob((value) => resolve(value!)))
    const body = new FormData()
    body.append('file', blob, 'fixture-avatar.png')
    const accessToken = JSON.parse(localStorage.getItem('session-store')!).state.tokens.accessToken
    const response = await fetch(`/api/users/${pilotId}/photo/upload`, {
      method: 'POST',
      body,
      headers: { Authorization: `Bearer ${accessToken}` },
    })
    return { status: response.status, photoUrl: (await response.json()).photoUrl as string }
  }, fixture.firstPilotId)
  expect(uploaded.status).toBe(200)
  const path = new URL(uploaded.photoUrl, 'http://localhost').pathname
  expect((await request.get(path)).status()).toBe(401)
  const mediaResponse = page.waitForResponse(
    (response) => new URL(response.url()).pathname === path,
  )
  await page.reload()
  const response = await mediaResponse
  expect(response.status()).toBe(200)
  expect(response.request().headers().authorization?.startsWith('Bearer ')).toBe(true)
  const avatar = page.getByRole('img', { name: 'Alpha, Alice avatar', exact: true })
  await expect(avatar).toHaveAttribute('src', /^blob:/)
  await expect
    .poll(() => avatar.evaluate((node) => (node as HTMLImageElement).naturalWidth))
    .toBe(8)
  const blobUrl = await avatar.getAttribute('src')
  await page.getByRole('button', { name: 'Logout', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Sign in', exact: true })).toBeVisible()
  await expect
    .poll(() =>
      page.evaluate(async (url) => {
        try {
          await fetch(url!)
          return true
        } catch {
          return false
        }
      }, blobUrl),
    )
    .toBe(false)
})

test('real API: nested route, profile, detail, authenticated PDF and analytics', async ({
  page,
}) => {
  const exceptions: string[] = []
  page.on('pageerror', (error) => exceptions.push(error.message))
  await signIn(page, `/pilots/${fixture.firstPilotId}/profile`)
  await expect(page.getByRole('heading', { name: 'Alice Alpha', exact: true })).toBeVisible()
  await expect(page.getByText('vue_alpha@example.com', { exact: true })).toBeVisible()
  await page.reload()
  await expect(page.getByRole('heading', { name: 'Alice Alpha', exact: true })).toBeVisible()
  await page.getByRole('link', { name: 'Training data', exact: true }).click()
  await expect(page.getByText('Latest training radar', { exact: true })).toBeVisible()
  await expect(page.locator('canvas')).not.toHaveCount(0)
  await page.goto(`/training-sessions/${fixture.training_id}`)
  await expect(
    page.getByRole('heading', { name: 'Comments and attempts', exact: true }),
  ).toBeVisible()
  const pdfResponse = page.waitForResponse((response) => response.url().includes('/report.pdf'))
  const popupPromise = page.waitForEvent('popup')
  await page.getByRole('button', { name: 'Export PDF', exact: true }).click()
  const popup = await popupPromise
  const response = await pdfResponse
  expect(response.status()).toBe(200)
  expect(response.request().headers().authorization?.startsWith('Bearer ')).toBe(true)
  expect(response.headers()['content-type']).toContain('application/pdf')
  await expect(popup.locator('iframe')).toHaveAttribute('src', /^blob:/)
  const blobUrl = await popup.locator('iframe').getAttribute('src')
  const pdf = await page.evaluate(async (url) => {
    const blob = await (await fetch(url!)).blob()
    return { size: blob.size, magic: await blob.slice(0, 5).text() }
  }, blobUrl)
  expect(pdf.magic).toBe('%PDF-')
  expect(pdf.size).toBeGreaterThan(1000)
  await popup.close()
  await page.getByRole('link', { name: 'Analytics', exact: true }).click()
  await expect(
    page.getByRole('heading', { name: 'Competency Overview', exact: true }),
  ).toBeVisible()
  await expect(page.locator('canvas')).toHaveCount(4)
  expect(exceptions).toEqual([])
})

test('real API: settings CRUD, threshold replacement and compatibility', async ({ page }) => {
  await signIn(page, '/settings')
  const name = `Integration ${Date.now()}`
  await page.getByLabel('New training type', { exact: true }).fill(name)
  await page.getByRole('button', { name: 'Create training type', exact: true }).click()
  await expect(page.getByLabel('Training type name', { exact: true })).toHaveValue(name)
  await page.getByLabel('Threshold', { exact: true }).first().fill('0')
  await page.getByRole('button', { name: 'Save thresholds', exact: true }).click()
  await expect(page.getByText('Up to date', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Make main', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Main threshold', exact: true })).toBeDisabled()
  await page.getByLabel('Training type name', { exact: true }).fill(`${name} edited`)
  await page.getByRole('button', { name: 'Save name', exact: true }).click()
  await expect(page.getByText('Up to date', { exact: true })).toBeVisible()
  await page.getByRole('link', { name: 'Compatibility', exact: true }).click()
  await page.getByRole('combobox', { name: 'CM 1', exact: true }).fill('vue_alpha')
  await page.getByRole('option', { name: /Alice Alpha/ }).click()
  await page.getByRole('combobox', { name: 'CM 2', exact: true }).fill('vue_bravo')
  await page.getByRole('option', { name: /Bob Bravo/ }).click()
  await page
    .getByRole('combobox', { name: 'Training type', exact: true })
    .selectOption({ label: `${name} edited` })
  await expect(page.getByText('Overall status', { exact: true })).toBeVisible()
  await expect(page.getByRole('alert')).toHaveCount(0)
  await page.getByRole('link', { name: 'Settings', exact: true }).click()
  await expect(page.getByLabel('Training type name', { exact: true })).toHaveValue(`${name} edited`)
  page.once('dialog', (dialog) => dialog.accept())
  await page.getByRole('button', { name: 'Delete', exact: true }).click()
  await page
    .getByRole('button')
    .filter({
      has: page.getByRole('heading', { name: 'Migration recurrent', exact: true, level: 4 }),
    })
    .click()
  await page.getByRole('button', { name: 'Make main', exact: true }).click()
})

test('real API: concurrent tabs recover an invalid access token with one refresh rotation', async ({
  page,
  context,
}) => {
  await signIn(page, '/pilots')
  await expect(page.getByRole('heading', { name: 'Pilots', exact: true })).toBeVisible()
  const oldRefresh = await page.evaluate(() => {
    const envelope = JSON.parse(localStorage.getItem('session-store')!)
    const refresh = envelope.state.tokens.refreshToken as string
    envelope.state.tokens.accessToken = 'invalid-access-for-integration'
    localStorage.setItem('session-store', JSON.stringify(envelope))
    return refresh
  })
  let rotations = 0
  context.on('request', (request) => {
    if (new URL(request.url()).pathname === '/api/auth/refresh') rotations++
  })
  const other = await context.newPage()
  await Promise.all([page.reload(), other.goto('/pilots')])
  for (const tab of [page, other]) {
    await expect(tab.getByRole('heading', { name: 'Pilots', exact: true })).toBeVisible()
    await expect
      .poll(() =>
        tab.evaluate(
          () =>
            JSON.parse(localStorage.getItem('session-store')!).state.tokens.refreshToken !== null,
        ),
      )
      .toBe(true)
  }
  const rotated = await page.evaluate(
    () => JSON.parse(localStorage.getItem('session-store')!).state.tokens.refreshToken as string,
  )
  expect(rotated === oldRefresh).toBe(false)
  expect(rotations).toBe(1)
  await page.getByRole('button', { name: 'Logout', exact: true }).click()
  await expect(other.getByRole('button', { name: 'Sign in', exact: true })).toBeVisible()
})
