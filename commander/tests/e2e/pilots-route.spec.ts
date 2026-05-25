import { expect, test } from '@playwright/test'

const makeMockUser = ({
  id,
  login,
  email,
  firstName,
  lastName,
}: {
  id: string
  login: string
  email: string
  firstName: string | null
  lastName: string | null
}) => ({
  id,
  login,
  email,
  isActive: true,
  mustChangePassword: false,
  createdAt: '2026-01-01T00:00:00.000Z',
  firstName,
  lastName,
  position: null,
  licenseNumber: null,
  phone: null,
  photoUrl: null,
  signatureUrl: null,
  airlineId: 1,
  roles: [],
  privileges: ['pilots:read', 'users:read'],
  aircraftIds: [],
  aircraftCodes: [],
})

test('uses last name ascending by default and restores its cached result after reset', async ({ page }) => {
  const requestedSorts: string[] = []

  await page.route('**/api/auth/login', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        tokenType: 'Bearer',
        accessToken: 'test-access-token',
        refreshToken: 'test-refresh-token',
      }),
    })
  })

  await page.route('**/api/auth/me', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(
        makeMockUser({
          id: '1',
          login: 'admin',
          email: 'admin@example.com',
          firstName: 'Admin',
          lastName: 'User',
        }),
      ),
    })
  })

  await page.route('**/api/commander/aircraft**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([]),
    })
  })

  await page.route('**/api/commander/pilots**', async (route) => {
    const url = new URL(route.request().url())
    requestedSorts.push(url.searchParams.get('sort') ?? '')

    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        total: 2,
        limit: 20,
        offset: 0,
        items: [
          makeMockUser({
            id: '2',
            login: 'alpha',
            email: 'alpha@example.com',
            firstName: 'Alice',
            lastName: 'Alpha',
          }),
          makeMockUser({
            id: '3',
            login: 'zulu',
            email: 'zulu@example.com',
            firstName: 'Zed',
            lastName: 'Zulu',
          }),
        ],
      }),
    })
  })

  await page.goto('/')
  await page.getByRole('textbox', { name: 'Login' }).fill('admin')
  await page.getByRole('textbox', { name: 'Password' }).fill('admin123')
  await page.getByRole('button', { name: 'Sign in' }).click()

  await expect(page.getByRole('heading', { name: 'Pilots' })).toBeVisible()
  await expect.poll(() => requestedSorts[0]).toBe('lastNameAsc')

  const sortSelect = page.getByRole('combobox', { name: 'Sort' })
  await expect(sortSelect).toHaveValue('lastNameAsc')

  await sortSelect.selectOption('loginDesc')
  await expect.poll(() => requestedSorts.at(-1)).toBe('loginDesc')

  await page.getByRole('button', { name: 'Reset filters' }).click()
  await expect(sortSelect).toHaveValue('lastNameAsc')
  await expect(page.getByRole('link', { name: 'Open Alpha, Alice profile in a new tab' })).toBeVisible()
  await expect(page.getByRole('link', { name: 'Open Zulu, Zed profile in a new tab' })).toBeVisible()
})
