import { expect, test } from '@playwright/test'
import { installMockApi, json, login, persistSession, tokenPair, user } from '../fixtures/mockApi'

test('shows startup loading while validating a persisted session without mounting private requests', async ({
  page,
}) => {
  const state = await installMockApi(page)
  await persistSession(page)
  let complete: (() => Promise<void>) | undefined
  await page.route('**/api/auth/me', (route) => {
    complete = () => json(route, state.currentUser)
  })
  await page.goto('/settings')
  await expect.poll(() => typeof complete).toBe('function')
  await expect(page.getByText('loading', { exact: true })).toBeVisible()
  expect(
    state.requests.filter((request) => request.path.startsWith('/api/commander/')),
  ).toHaveLength(0)
  await complete!()
  await expect(page.getByRole('heading', { name: 'Settings', exact: true, level: 1 })).toBeVisible()
  await expect(page.getByText('loading', { exact: true })).toHaveCount(0)
  await expect(page).toHaveURL(/\/settings$/)
})

test('keeps the protected deep link through login and rejects invalid detail IDs without a request', async ({
  page,
}) => {
  const state = await installMockApi(page)
  await login(page, '/training-sessions/not-an-id')
  await expect(page).toHaveURL(/\/training-sessions\/not-an-id$/)
  await expect(page.getByText('Training session id is invalid.')).toBeVisible()
  expect(state.requests.some((request) => request.path.endsWith('/not-an-id'))).toBe(false)
})

test('login failure allows retry and double submission makes a single request', async ({
  page,
}) => {
  await installMockApi(page)
  let calls = 0
  let release: (() => Promise<void>) | undefined
  await page.route('**/api/auth/login', async (route) => {
    calls++
    if (calls === 1) return json(route, { detail: 'Invalid credentials' }, 401)
    release = () => json(route, tokenPair)
  })
  await login(page)
  await expect(page.getByRole('alert')).toContainText('Invalid credentials')
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await expect.poll(() => calls).toBe(2)
  await expect(page.getByRole('button', { name: 'Sign in...', exact: true })).toBeDisabled()
  await page.getByLabel('Password', { exact: true }).press('Enter')
  expect(calls).toBe(2)
  await release!()
  await expect(page.getByRole('heading', { name: 'Pilots', exact: true })).toBeVisible()
})

test('revalidates persisted privileges before rendering protected content', async ({ page }) => {
  const state = await installMockApi(page, ['pilots:read'])
  await persistSession(page, user('admin', ['pilots:read', 'users:read']))
  await page.goto('/admin')
  await expect(page).toHaveURL(/\/forbidden$/)
  await expect(page.getByRole('link', { name: 'Admin', exact: true })).toHaveCount(0)
  expect(state.requests.filter((request) => request.path === '/api/auth/me')).toHaveLength(1)
  await page.getByRole('link', { name: 'Pilots', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Pilots', exact: true })).toBeVisible()
})

test('shows retry/logout after profile failure and never mounts domain requests before verification', async ({
  page,
}) => {
  const state = await installMockApi(page)
  await persistSession(page)
  let fail = true
  await page.route('**/api/auth/me', (route) =>
    json(route, fail ? { detail: 'Service unavailable' } : state.currentUser, fail ? 503 : 200),
  )
  await page.goto('/pilots')
  await expect(page.getByRole('heading', { name: 'Session check failed' })).toBeVisible()
  expect(
    state.requests.filter((request) => request.path.startsWith('/api/commander/')),
  ).toHaveLength(0)
  fail = false
  await page.getByRole('button', { name: 'Try again', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Pilots', exact: true })).toBeVisible()
})

test('clears rejected refresh and permits login on the original deep link', async ({ page }) => {
  await installMockApi(page)
  await persistSession(page)
  await page.route('**/api/auth/me', (route) => json(route, { detail: 'Expired' }, 401))
  await page.route('**/api/auth/refresh', (route) =>
    json(route, { detail: 'Session revoked' }, 401),
  )
  await page.goto('/settings')
  await expect(page.getByRole('button', { name: 'Sign in', exact: true })).toBeVisible()
  await expect(page).toHaveURL(/\/settings$/)
  expect(
    await page.evaluate(() => JSON.parse(localStorage.getItem('session-store')!).state),
  ).toEqual({ tokens: null, user: null, privileges: [] })
})

test('broadcasts logout to another tab and removes both protected trees', async ({
  page,
  context,
}) => {
  await installMockApi(page)
  await login(page)
  await expect(page.getByRole('heading', { name: 'Pilots', exact: true })).toBeVisible()
  const second = await context.newPage()
  await installMockApi(second)
  await second.goto('/settings')
  await expect(
    second.getByRole('heading', { name: 'Settings', exact: true, level: 1 }),
  ).toBeVisible()
  await page.getByRole('button', { name: 'Logout', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Sign in', exact: true })).toBeVisible()
  await expect(second.getByRole('button', { name: 'Sign in', exact: true })).toBeVisible()
  await expect(second.getByRole('heading', { name: 'Recurrent', exact: true })).toHaveCount(0)
})

for (const path of ['/', '/unknown-page']) {
  test(`redirects ${path} to pilots`, async ({ page }) => {
    await installMockApi(page)
    await login(page, path)
    await expect(page).toHaveURL(/\/pilots$/)
    await expect(page.getByRole('heading', { name: 'Pilots', exact: true })).toBeVisible()
  })
}
