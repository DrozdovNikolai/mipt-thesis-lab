import { expect, test } from '@playwright/test'
import { installMockApi, json, login, persistSession, user } from '../fixtures/mockApi'

test('login recovers from a network failure without losing the deep link', async ({ page }) => {
  await installMockApi(page)
  await page.route('**/api/auth/login', (route) => route.abort('failed'), { times: 1 })
  await login(page, '/settings')
  await expect(page.getByRole('alert')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Sign in', exact: true })).toBeEnabled()
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Settings', exact: true, level: 1 })).toBeVisible()
  await expect(page).toHaveURL(/\/settings$/)
})

for (const failure of ['network', 'forbidden']) {
  test(`bootstrap ${failure} cannot expose cached privileges and supports retry`, async ({
    page,
  }) => {
    const state = await installMockApi(page)
    await persistSession(page)
    await page.route(
      '**/api/auth/me',
      (route) =>
        failure === 'network'
          ? route.abort('failed')
          : json(route, { detail: 'Verification denied' }, 403),
      { times: 1 },
    )
    await page.goto('/admin')
    await expect(
      page.getByRole('heading', { name: 'Session check failed', exact: true }),
    ).toBeVisible()
    expect(state.requests.some((request) => request.path.startsWith('/api/commander/'))).toBe(false)
    await page.getByRole('button', { name: 'Try again', exact: true }).click()
    await expect(page.getByRole('heading', { name: 'Admin', exact: true })).toBeVisible()
  })
}

test('pilot pagination, activity and filters reset offsets atomically; lookup failure leaves rows usable', async ({
  page,
}) => {
  await installMockApi(page)
  const calls: Record<string, string>[] = []
  await page.route('**/api/commander/pilots?**', (route) => {
    const query = Object.fromEntries(new URL(route.request().url()).searchParams)
    calls.push(query)
    return json(route, {
      total: 125,
      offset: Number(query.offset),
      limit: Number(query.limit),
      items: [user('alpha')],
    })
  })
  await login(page)
  await expect.poll(() => calls.length).toBe(1)
  expect(calls[0]).toMatchObject({ sort: 'lastNameAsc', offset: '0', limit: '20' })
  expect(calls[0]).not.toHaveProperty('isActive')
  await page.getByRole('button', { name: 'Next', exact: true }).click()
  await expect.poll(() => calls.at(-1)?.offset).toBe('20')
  await page.getByRole('combobox', { name: 'Status', exact: true }).selectOption('inactive')
  await expect.poll(() => calls.at(-1)).toMatchObject({ isActive: 'false', offset: '0' })
  expect(calls.some((call) => call.isActive === 'false' && call.offset !== '0')).toBe(false)
  await page.getByRole('combobox', { name: 'Status', exact: true }).selectOption('active')
  await expect.poll(() => calls.at(-1)?.isActive).toBe('true')
  await page.getByRole('combobox', { name: 'Aircraft', exact: true }).selectOption('1')
  await expect.poll(() => calls.at(-1)?.aircraftId).toBe('1')
  await page.getByRole('combobox', { name: 'Page size', exact: true }).selectOption('50')
  await expect.poll(() => calls.at(-1)?.limit).toBe('50')
  await page.getByRole('button', { name: 'Next', exact: true }).click()
  await expect.poll(() => calls.at(-1)?.offset).toBe('50')
  await page.getByRole('button', { name: 'Next', exact: true }).click()
  await expect.poll(() => calls.at(-1)?.offset).toBe('100')
  await expect(page.getByRole('button', { name: 'Next', exact: true })).toBeDisabled()
  await expect(page.getByText('Showing 101-125 of 125', { exact: true })).toBeVisible()
  await page.getByRole('textbox', { name: 'Search', exact: true }).fill('Anna')
  await expect.poll(() => calls.at(-1)?.q).toBe('Anna')
  expect(calls.filter((call) => call.q === 'Anna').every((call) => call.offset === '0')).toBe(true)
  await page.getByRole('button', { name: 'Reset filters', exact: true }).click()
  await expect(page.getByRole('combobox', { name: 'Page size', exact: true })).toHaveValue('20')
  await page.route('**/api/commander/aircraft', (route) =>
    json(route, { detail: 'Aircraft lookup unavailable' }, 503),
  )
  await page.reload()
  await expect(page.getByRole('alert')).toContainText('Aircraft lookup unavailable')
  await expect(
    page.getByRole('link', { name: 'Open Adams, Anna profile in a new tab', exact: true }),
  ).toBeVisible()
})

test('media retry and a new airline session never reuse the previous Blob', async ({ page }) => {
  const state = await installMockApi(page)
  let photoUrl = '/api/users/photos/shared.png'
  await page.route('**/api/commander/pilots?**', (route) =>
    json(route, { total: 1, offset: 0, limit: 20, items: [{ ...user('alpha'), photoUrl }] }),
  )
  let calls = 0
  await page.route('**/api/users/photos/*.png', (route) => {
    calls++
    if (calls === 1) return json(route, { detail: 'Temporary media error' }, 503)
    expect(route.request().headers().authorization).toBe('Bearer mock-access')
    return route.fulfill({
      contentType: 'image/svg+xml',
      body: `<svg xmlns="http://www.w3.org/2000/svg" width="${state.currentUser.airlineId}" height="1"></svg>`,
    })
  })
  await login(page)
  const avatar = page.getByRole('img', { name: 'Adams, Anna avatar', exact: true })
  await expect(avatar).toHaveAttribute('src', /^blob:/)
  expect(calls).toBe(2)
  const previousBlob = await avatar.getAttribute('src')
  await page.clock.install()
  photoUrl = '/api/users/photos/replaced.png'
  await page.clock.fastForward(31_000)
  await page.evaluate(() => {
    window.dispatchEvent(new Event('offline'))
    window.dispatchEvent(new Event('online'))
  })
  await expect.poll(() => calls).toBe(3)
  await expect(avatar).not.toHaveAttribute('src', previousBlob!)
  expect(
    await page.evaluate(async (url) => {
      try {
        await fetch(url!)
        return true
      } catch {
        return false
      }
    }, previousBlob),
  ).toBe(false)
  const replacementBlob = await avatar.getAttribute('src')
  await page.getByRole('button', { name: 'Logout', exact: true }).click()
  state.currentUser = { ...state.currentUser, id: 'other-user', airlineId: 2 }
  await login(page)
  await expect.poll(() => calls).toBe(4)
  await expect
    .poll(() => avatar.evaluate((image) => (image as HTMLImageElement).naturalWidth))
    .toBeGreaterThan(0)
  // SVG intrinsic sizing differs across engines; verify the actual second-session bytes.
  expect(
    await avatar.evaluate(async (image) => (await fetch((image as HTMLImageElement).src)).text()),
  ).toContain('width="2"')
  expect(await avatar.getAttribute('src')).not.toBe(previousBlob)
  expect(
    await page.evaluate(async (url) => {
      try {
        await fetch(url!)
        return true
      } catch {
        return false
      }
    }, replacementBlob),
  ).toBe(false)
})

test('settings retains drafts on 422, suppresses duplicate save, and deletes the final type', async ({
  page,
}) => {
  const state = await installMockApi(page)
  state.flightTypes = state.flightTypes.slice(0, 1)
  await login(page, '/settings')
  await page.getByLabel('Training type name', { exact: true }).fill('Pending name')
  let calls = 0
  let complete: (() => Promise<void>) | undefined
  await page.route('**/api/commander/flight-types/1', async (route) => {
    if (route.request().method() !== 'PUT' && route.request().method() !== 'PATCH')
      return route.fallback()
    calls++
    complete = () => json(route, { detail: 'Name rejected by server' }, 422)
  })
  await page.getByRole('button', { name: 'Save name', exact: true }).click()
  await expect.poll(() => calls).toBe(1)
  await expect(page.getByRole('button', { name: 'Saving...', exact: true })).toBeDisabled()
  await page.getByLabel('Training type name', { exact: true }).press('Enter')
  expect(calls).toBe(1)
  await complete!()
  await expect(page.getByRole('alert')).toHaveText('Name rejected by server')
  await expect(page.getByLabel('Training type name', { exact: true })).toHaveValue('Pending name')
  page.once('dialog', (dialog) => dialog.accept())
  await page.getByRole('button', { name: 'Delete', exact: true }).click()
  await expect.poll(() => state.flightTypes.length).toBe(0)
  await expect(page.getByLabel('Training type name', { exact: true })).toHaveCount(0)
  await expect(page.getByLabel('New training type', { exact: true })).toBeEnabled()
})

test('autocomplete Escape and Tab leave focus usable without selecting a pilot', async ({
  page,
}) => {
  await installMockApi(page)
  await login(page, '/compatibility')
  const first = page.getByRole('combobox', { name: 'CM 1', exact: true })
  await first.fill('Anna')
  await expect(page.getByRole('option', { name: /Anna Adams/ })).toBeVisible()
  await first.press('ArrowDown')
  await first.press('Escape')
  await expect(page.getByRole('listbox')).toHaveCount(0)
  await expect(first).toHaveAttribute('aria-expanded', 'false')
  await expect(first).toBeFocused()
  await first.press('Tab')
  await expect(first).not.toBeFocused()
  await expect(page.getByText('Overall status', { exact: true })).toHaveCount(0)
})

test('a late response for the previous search cannot replace the current pilot list', async ({
  page,
}) => {
  await installMockApi(page)
  let oldRequestStarted = false
  let release: (() => Promise<void>) | undefined
  await page.route('**/api/commander/pilots?**', (route) => {
    const q = new URL(route.request().url()).searchParams.get('q')
    const response = {
      total: 1,
      limit: 20,
      offset: 0,
      items: [{ ...user('alpha'), firstName: q === 'New' ? 'New' : 'Old', lastName: 'Search' }],
    }
    if (q === 'Old') {
      oldRequestStarted = true
      release = () => json(route, response)
      return
    }
    return json(route, response)
  })
  await login(page)
  await page.getByRole('textbox', { name: 'Search', exact: true }).fill('Old')
  await expect.poll(() => oldRequestStarted).toBe(true)
  await page.getByRole('textbox', { name: 'Search', exact: true }).fill('New')
  await expect(
    page.getByRole('link', { name: 'Open Search, New profile in a new tab', exact: true }),
  ).toBeVisible()
  await release!()
  await expect(
    page.getByRole('link', { name: 'Open Search, New profile in a new tab', exact: true }),
  ).toBeVisible()
  await expect(
    page.getByRole('link', { name: 'Open Search, Old profile in a new tab', exact: true }),
  ).toHaveCount(0)
  await expect(page.getByRole('alert')).toHaveCount(0)
})

test('403 save and rejected deletion retain the selected settings draft', async ({ page }) => {
  const state = await installMockApi(page)
  await login(page, '/settings')
  await page.getByLabel('Training type name', { exact: true }).fill('Private draft')
  await page.route('**/api/commander/flight-types/1', (route) =>
    json(route, { detail: 'Permission removed by server' }, 403),
  )
  await page.getByRole('button', { name: 'Save name', exact: true }).click()
  await expect(page.getByRole('alert')).toHaveText('Permission removed by server')
  await expect(page.getByLabel('Training type name', { exact: true })).toHaveValue('Private draft')
  page.once('dialog', (dialog) => dialog.accept())
  await page.getByRole('button', { name: 'Delete', exact: true }).click()
  await expect(page.getByRole('alert')).toHaveText('Permission removed by server')
  await expect(page.getByLabel('Training type name', { exact: true })).toHaveValue('Private draft')
  expect(state.flightTypes).toHaveLength(2)
})

test('autocomplete exposes loading and empty results and closes with Escape', async ({ page }) => {
  await installMockApi(page)
  let complete: (() => Promise<void>) | undefined
  await page.route('**/api/commander/pilots?**', (route) => {
    complete = () => json(route, { total: 0, limit: 10, offset: 0, items: [] })
  })
  await login(page, '/compatibility')
  const input = page.getByRole('combobox', { name: 'CM 1', exact: true })
  await input.click()
  await expect(page.getByRole('status')).toHaveText('Loading...')
  await expect.poll(() => typeof complete).toBe('function')
  await complete!()
  await expect(page.getByText('No matches found.', { exact: true })).toBeVisible()
  await input.press('ArrowDown')
  await input.press('Enter')
  await expect(page.getByText('Overall status', { exact: true })).toHaveCount(0)
  await input.press('Escape')
  await expect(input).toHaveAttribute('aria-expanded', 'false')
  await expect(input).toBeFocused()
})
