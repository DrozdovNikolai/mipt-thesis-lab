// Fixtures extracted from the verified React baseline: pilots-route.spec.ts
// Source SHA-256: f6a8e58df887aece9b76df3590da5df187bb1af24df9c90d5e7a747ef37a3594
import type { Page } from '@playwright/test'

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

export async function installPilotsFixtures(page: Page) {

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

  
}
