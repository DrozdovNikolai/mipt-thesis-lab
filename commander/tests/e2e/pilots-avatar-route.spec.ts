import { expect, test } from '@playwright/test'

const ONE_PIXEL_SVG = '<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"></svg>'

type MockUserOverrides = {
  id: string
  login: string
  email: string
  firstName: string | null
  lastName: string | null
  photoUrl: string | null
  aircraftCodes: string[]
  position?: string | null
}

const makeMockUser = ({
  id,
  login,
  email,
  firstName,
  lastName,
  photoUrl,
  aircraftCodes,
  position = null,
}: MockUserOverrides) => ({
  id,
  login,
  email,
  isActive: true,
  mustChangePassword: false,
  createdAt: '2026-01-01T00:00:00.000Z',
  firstName,
  lastName,
  position,
  licenseNumber: null,
  phone: null,
  photoUrl,
  signatureUrl: null,
  airlineId: 1,
  roles: [],
  privileges: ['pilots:read', 'users:read'],
  aircraftIds: [1],
  aircraftCodes,
})

test('keeps loaded avatar visible after route switches and does not re-fetch missing photos', async ({ page }) => {
  let missingPhotoRequests = 0
  const blobErrors: string[] = []

  page.on('console', (message) => {
    if (message.type() === 'error' && message.text().includes('blob:')) {
      blobErrors.push(message.text())
    }
  })

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
          photoUrl: null,
          aircraftCodes: ['B737'],
        }),
      ),
    })
  })

  await page.route('**/api/commander/aircraft**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([
        { id: 1, code: 'B737', name: 'Boeing 737 Long Production Aircraft Name', active: true, airlineId: 1 },
      ]),
    })
  })

  await page.route('**/api/commander/pilots**', async (route) => {
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
            login: 'photo.pilot',
            email: 'photo.pilot@example.com',
            firstName: 'Photo',
            lastName: 'Pilot',
            photoUrl: '/api/users/photos/existing.png',
            aircraftCodes: ['B737'],
            position: 'Captain',
          }),
          makeMockUser({
            id: '3',
            login: 'missing.pilot',
            email: 'missing.pilot@example.com',
            firstName: 'Missing',
            lastName: 'Pilot',
            photoUrl: '/api/users/photos/missing.png',
            aircraftCodes: ['B737'],
            position: 'First officer',
          }),
        ],
      }),
    })
  })

  await page.route('**/api/users/photos/existing.png', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'image/svg+xml',
      body: ONE_PIXEL_SVG,
    })
  })

  await page.route('**/api/users/photos/missing.png', async (route) => {
    missingPhotoRequests += 1
    await route.fulfill({
      status: 404,
      contentType: 'application/json',
      body: JSON.stringify({ detail: 'Not Found' }),
    })
  })

  await page.goto('/')
  await page.getByRole('textbox', { name: 'Login' }).fill('admin')
  await page.getByRole('textbox', { name: 'Password' }).fill('admin123')
  await page.getByRole('button', { name: 'Sign in' }).click()

  const loadedAvatar = page.getByRole('img', { name: 'Pilot, Photo avatar' })
  const missingPilotRow = page.getByRole('link', {
    name: 'Open Pilot, Missing profile in a new tab',
  })
  const aircraftSelect = page.getByRole('combobox', { name: 'Aircraft' })

  await expect(loadedAvatar).toBeVisible()
  await expect(aircraftSelect.locator('option')).toHaveText(['All aircraft', 'B737'])
  await expect
    .poll(async () => loadedAvatar.evaluate((node) => (node as HTMLImageElement).naturalWidth))
    .toBeGreaterThan(0)
  await expect(missingPilotRow.getByText('MP', { exact: true })).toBeVisible()

  const missingRequestsAfterFirstLoad = missingPhotoRequests
  expect(missingRequestsAfterFirstLoad).toBeGreaterThan(0)

  await page.getByRole('link', { name: 'Admin' }).click()
  await expect(page.getByRole('heading', { name: 'Admin' })).toBeVisible()
  await page.getByRole('link', { name: 'Pilots' }).click()

  await expect(loadedAvatar).toBeVisible()
  await expect
    .poll(async () => loadedAvatar.evaluate((node) => (node as HTMLImageElement).naturalWidth))
    .toBeGreaterThan(0)
  await expect(missingPilotRow.getByText('MP', { exact: true })).toBeVisible()

  expect(missingPhotoRequests).toBe(missingRequestsAfterFirstLoad)
  expect(blobErrors).toEqual([])
})
