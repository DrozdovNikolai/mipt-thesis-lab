import { expect, test, type Page } from '@playwright/test'
import { installMockApi, json, login } from '../fixtures/mockApi'

test('preserves independent name/threshold drafts and saves hidden fields in the replace payload', async ({
  page,
}) => {
  const state = await installMockApi(page)
  await login(page, '/settings')
  await expect(page.getByLabel('Training type name', { exact: true })).toHaveValue('Recurrent')
  await page.getByLabel('Training type name', { exact: true }).fill('  Recurrent   revised  ')
  await page
    .getByRole('article')
    .filter({ has: page.getByRole('heading', { name: 'Operations', exact: true }) })
    .getByLabel('Threshold', { exact: true })
    .fill('0.')
  await page.getByRole('button', { name: 'Save name', exact: true }).click()
  await expect(page.getByLabel('Training type name', { exact: true })).toHaveValue(
    'Recurrent revised',
  )
  await expect(page.getByText('Unsaved changes', { exact: true })).toBeVisible()
  await page.getByLabel('Filter competences').fill('OPS')
  await page.getByRole('button', { name: 'Save thresholds', exact: true }).click()
  await expect
    .poll(() => state.requests.filter((r) => r.path.endsWith('/thresholds')).at(-1)?.body)
    .toEqual({
      thresholds: [
        { competenceId: 1, value: '0' },
        { competenceId: 2, value: '6' },
      ],
    })
  await expect(page.getByText('Up to date', { exact: true })).toBeVisible()
  await page.getByLabel('Training type name', { exact: true }).fill('Local name')
  await page
    .getByRole('article')
    .filter({ has: page.getByRole('heading', { name: 'Operations', exact: true }) })
    .getByLabel('Threshold', { exact: true })
    .fill('8')
  await page.getByRole('button', { name: 'Save thresholds', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Save thresholds', exact: true })).toBeDisabled()
  await expect(page.getByLabel('Training type name', { exact: true })).toHaveValue('Local name')
  await page
    .getByRole('button')
    .filter({ has: page.getByRole('heading', { name: 'Upgrade', exact: true }) })
    .click()
  await page.getByLabel('Training type name', { exact: true }).fill('Upgrade local')
  await page
    .getByRole('button')
    .filter({
      has: page.getByRole('heading', { name: 'Recurrent revised', exact: true, level: 4 }),
    })
    .click()
  await expect(page.getByLabel('Training type name', { exact: true })).toHaveValue('Local name')
  await page.getByRole('button', { name: 'Reset draft', exact: true }).click()
  await expect(page.getByLabel('Training type name', { exact: true })).toHaveValue(
    'Recurrent revised',
  )
  await page
    .getByRole('button')
    .filter({ has: page.getByRole('heading', { name: 'Upgrade', exact: true }) })
    .click()
  await expect(page.getByLabel('Training type name', { exact: true })).toHaveValue('Upgrade local')
})

test('creates, makes the only main type, survives failed save, and confirms deletion', async ({
  page,
}) => {
  const state = await installMockApi(page)
  await login(page, '/settings')
  await expect(
    page.getByRole('button', { name: 'Create training type', exact: true }),
  ).toBeDisabled()
  await page.getByLabel('New training type', { exact: true }).fill('  Line   check  ')
  await page.getByRole('button', { name: 'Create training type', exact: true }).click()
  await expect(page.getByLabel('Training type name', { exact: true })).toHaveValue('Line check')
  await page.getByRole('button', { name: 'Make main', exact: true }).click()
  await expect
    .poll(() => state.flightTypes.filter((item) => item.isMain).map((item) => item.name))
    .toEqual(['Line check'])
  state.failNextWrite = true
  await page.getByLabel('Training type name', { exact: true }).fill('Edited name')
  await page.getByRole('button', { name: 'Save name', exact: true }).click()
  await expect(page.getByRole('alert')).toHaveText('Write failed, please retry.')
  await expect(page.getByLabel('Training type name', { exact: true })).toHaveValue('Edited name')
  await page.getByRole('button', { name: 'Save name', exact: true }).click()
  await expect(page.getByText('Up to date', { exact: true })).toBeVisible()
  page.once('dialog', (dialog) => dialog.dismiss())
  await page.getByRole('button', { name: 'Delete', exact: true }).click()
  expect(state.flightTypes).toHaveLength(3)
  page.once('dialog', (dialog) => dialog.accept())
  await page.getByRole('button', { name: 'Delete', exact: true }).click()
  await expect.poll(() => state.flightTypes.length).toBe(2)
  await expect(page.getByLabel('Training type name', { exact: true })).not.toHaveValue(
    'Edited name',
  )
})

test('read-only privileges allow settings inspection without write actions', async ({ page }) => {
  const state = await installMockApi(page, ['pilots:read'])
  await login(page, '/settings')
  await expect(page.getByText('You have read-only access to training types.')).toBeVisible()
  await expect(page.getByLabel('Training type name', { exact: true })).toBeDisabled()
  await expect(page.getByRole('button', { name: 'Delete', exact: true })).toBeDisabled()
  expect(
    state.requests.filter((r) => r.path.includes('flight-types') && r.method !== 'GET'),
  ).toHaveLength(0)
})

async function choosePair(page: Page) {
  await page.getByRole('combobox', { name: 'CM 1', exact: true }).fill('alpha@example.test')
  // Remote results may match by email even though their visible label is a name.
  await page.getByRole('option', { name: /Anna Adams/ }).click()
  await page.getByRole('combobox', { name: 'CM 2', exact: true }).click()
  await expect(page.getByRole('option', { name: /Anna Adams/ })).toHaveCount(0)
  await page.getByRole('combobox', { name: 'CM 2', exact: true }).press('ArrowDown')
  await page.getByRole('combobox', { name: 'CM 2', exact: true }).press('Enter')
  await expect(page.getByRole('combobox', { name: 'CM 2', exact: true })).toHaveValue('Boris Brown')
  await page.getByRole('combobox', { name: 'Training type', exact: true }).selectOption('1')
}

test('distinguishes unconfigured thresholds, missing grades, and a failed comparison', async ({
  page,
}) => {
  const state = await installMockApi(page)
  state.flightTypes[0]!.thresholds = []
  await login(page, '/compatibility')
  await choosePair(page)
  await expect(page.getByText('Thresholds not configured', { exact: true })).toBeVisible()
  await expect(page.getByText('0/0 compatible', { exact: true })).toBeVisible()
  await page.route('**/api/commander/pilots/compatibility?**', async (route) => {
    if (new URL(route.request().url()).searchParams.get('asOfDate') === '2026-02-01') {
      return json(route, { detail: 'Comparison temporarily unavailable' }, 503)
    }
    return json(route, {
      firstPilot: {
        id: 'alpha',
        firstName: 'Anna',
        lastName: 'Adams',
        hasCompletedTraining: false,
      },
      secondPilot: {
        id: 'beta',
        firstName: 'Boris',
        lastName: 'Brown',
        hasCompletedTraining: true,
      },
      flightType: state.flightTypes[0],
      asOfDate: '2026-01-01',
      items: [
        {
          competenceId: 1,
          competenceCode: 'OPS',
          competenceName: 'Operations',
          orderIndex: 1,
          thresholdConfigured: true,
          compatible: false,
          requiredSum: 0,
          actualSum: null,
          firstPilotValue: null,
          secondPilotValue: 0,
        },
      ],
    })
  })
  await page.getByLabel('As of date', { exact: true }).fill('2026-01-01')
  await expect(page.getByText('No completed training', { exact: true })).toBeVisible()
  await expect(page.getByText('No grade', { exact: true })).toBeVisible()
  await expect(page.getByText('Missing data', { exact: true })).toBeVisible()
  await expect(page.getByText('Not compatible', { exact: true })).toBeVisible()
  await page.getByLabel('As of date', { exact: true }).fill('2026-02-01')
  await expect(page.getByText('Comparison temporarily unavailable', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Reset', exact: true }).click()
  await expect(page.getByText('Overall status', { exact: true })).toHaveCount(0)
  await expect(page.getByText('Comparison temporarily unavailable', { exact: true })).toHaveCount(0)
})

test('compares selected IDs, prevents duplicates, keeps date on reset, and removes invalidated result', async ({
  page,
}) => {
  const state = await installMockApi(page)
  await login(page, '/compatibility')
  await choosePair(page)
  await expect(page.getByText('Not compatible', { exact: true })).toBeVisible()
  await page.getByLabel('As of date', { exact: true }).fill('2026-03-01')
  await expect
    .poll(
      () => state.requests.filter((r) => r.path.endsWith('/pilots/compatibility')).at(-1)?.query,
    )
    .toEqual({
      firstPilotId: 'alpha',
      secondPilotId: 'beta',
      flightTypeId: '1',
      asOfDate: '2026-03-01',
    })
  await page.getByRole('button', { name: 'Clear CM 1', exact: true }).click()
  await expect(page.getByText('Overall status', { exact: true })).toHaveCount(0)
  await page.getByRole('button', { name: 'Reset', exact: true }).click()
  await expect(page.getByLabel('As of date', { exact: true })).toHaveValue('2026-03-01')
  await expect(page.getByRole('combobox', { name: 'CM 2', exact: true })).toHaveValue('')
})

test('uses updated thresholds after saving settings and returning to compatibility', async ({
  page,
}) => {
  await installMockApi(page)
  await login(page, '/compatibility')
  await choosePair(page)
  await expect(page.getByText('Not compatible', { exact: true })).toBeVisible()
  await page.getByRole('link', { name: 'Settings', exact: true }).click()
  await page
    .getByRole('article')
    .filter({ has: page.getByRole('heading', { name: 'Operations', exact: true }) })
    .getByLabel('Threshold', { exact: true })
    .fill('0')
  await page.getByRole('button', { name: 'Save thresholds', exact: true }).click()
  await expect(page.getByText('Up to date', { exact: true })).toBeVisible()
  await page.getByRole('link', { name: 'Compatibility', exact: true }).click()
  await choosePair(page)
  await expect(page.getByText('2/2 compatible', { exact: true })).toBeVisible()
  await expect(page.getByText('Not compatible', { exact: true })).toHaveCount(0)
})

test('clears a removed training type after network reconnect revalidation', async ({ page }) => {
  await page.clock.install()
  const state = await installMockApi(page)
  await login(page, '/compatibility')
  await choosePair(page)
  await expect(page.getByText('Overall status', { exact: true })).toBeVisible()
  state.flightTypes = state.flightTypes.filter((type) => type.id !== 1)
  await page.clock.fastForward(31_000)
  await page.evaluate(() => {
    window.dispatchEvent(new Event('offline'))
    window.dispatchEvent(new Event('online'))
  })
  await expect
    .poll(
      () =>
        state.requests.filter((request) => request.path === '/api/commander/flight-types').length,
    )
    .toBe(2)
  await expect(
    page.getByRole('combobox', { name: 'Training type', exact: true }).locator('option:checked'),
  ).toHaveText('Select type')
  await expect(page.getByText('Overall status', { exact: true })).toHaveCount(0)
})
