import type { Page, Route } from '@playwright/test'
import type { SessionUser } from '../../src/entities/session/types'
import type { CommanderFlightType, PilotCompatibilityResponse } from '../../src/entities/commander/types'
import type { Competence } from '../../src/entities/training/types'
export const timestamp = '2026-01-01T00:00:00.000Z'
export const user = (id = 'admin', privileges = ['pilots:read', 'pilots:write', 'users:read']): SessionUser => ({ id, login: id, email: `${id}@example.test`, firstName: id === 'alpha' ? 'Anna' : id === 'beta' ? 'Boris' : 'Admin', lastName: id === 'alpha' ? 'Adams' : id === 'beta' ? 'Brown' : 'User', airlineId: 1, isActive: true, mustChangePassword: false, createdAt: timestamp, position: 'Captain', licenseNumber: null, phone: null, photoUrl: null, signatureUrl: null, roles: [], privileges, aircraftIds: [1], aircraftCodes: ['B737'] })
export const tokenPair = { tokenType: 'Bearer', accessToken: 'mock-access', refreshToken: 'mock-refresh' }
export const competences: Competence[] = [{ id: 1, code: 'OPS', name: 'Operations', description: 'Operational knowledge', orderIndex: 1, createdAt: timestamp, updatedAt: timestamp }, { id: 2, code: 'CRM', name: 'Crew Resource Management', description: null, orderIndex: 2, createdAt: timestamp, updatedAt: timestamp }]
export const threshold = (competenceId: number, value: string | number) => ({ id: competenceId, competenceId, competenceCode: competences.find(item => item.id === competenceId)!.code, competenceName: competences.find(item => item.id === competenceId)!.name, competenceOrderIndex: competenceId, value, createdAt: timestamp, updatedAt: timestamp })
export const initialTypes = (): CommanderFlightType[] => [{ id: 1, airlineId: 1, name: 'Recurrent', isMain: true, createdAt: timestamp, updatedAt: timestamp, thresholds: [threshold(1, '7'), threshold(2, '6')] }, { id: 2, airlineId: 1, name: 'Upgrade', isMain: false, createdAt: timestamp, updatedAt: timestamp, thresholds: [] }]
export const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
export async function installMockApi(page: Page, privileges = ['pilots:read', 'pilots:write', 'users:read']) {
  const state = { currentUser: user('admin', privileges), flightTypes: initialTypes(), requests: [] as { path: string; method: string; query: Record<string, string>; body: unknown; authorization: string | undefined }[], failNextWrite: false }
  await page.route('**/api/**', async route => {
    const request = route.request(), url = new URL(request.url()), path = url.pathname, method = request.method()
    const body = request.postData() ? request.postDataJSON() : null
    state.requests.push({ path, method, body, query: Object.fromEntries(url.searchParams), authorization: request.headers().authorization })
    if (path === '/api/auth/login') return json(route, tokenPair)
    if (path === '/api/auth/me') return json(route, state.currentUser)
    if (path === '/api/auth/refresh') return json(route, tokenPair)
    if (!request.headers().authorization) return json(route, { detail: 'Bearer missing' }, 401)
    if (path === '/api/commander/aircraft' || path === '/api/training/aircraft') return json(route, [{ id: 1, airlineId: 1, code: 'B737', name: 'Boeing 737', colorHex: '#284692', active: true }])
    if (path === '/api/users/positions') return json(route, [{ id: 1, name: 'Captain', airlineId: 1 }])
    if (path === '/api/commander/pilots') return json(route, { total: 2, limit: Number(url.searchParams.get('limit') || 20), offset: Number(url.searchParams.get('offset') || 0), items: [user('alpha'), user('beta')] })
    if (path === '/api/commander/competences') return json(route, competences)
    if (path.startsWith('/api/commander/flight-types')) {
      const id = Number(path.split('/')[4]), existing = state.flightTypes.find(item => item.id === id)
      if (method !== 'GET' && state.failNextWrite) { state.failNextWrite = false; return json(route, { detail: 'Write failed, please retry.' }, 500) }
      if (method !== 'GET' && !state.currentUser.privileges.includes('pilots:write')) return json(route, { detail: 'Not allowed' }, 403)
      if (method === 'GET') return json(route, state.flightTypes)
      if (method === 'POST') { const item = { id: Math.max(0, ...state.flightTypes.map(item => item.id)) + 1, airlineId: 1, name: body.name, isMain: false, createdAt: timestamp, updatedAt: timestamp, thresholds: [] }; state.flightTypes.push(item); return json(route, item, 201) }
      if (!existing) return json(route, { detail: 'Not found' }, 404)
      if (method === 'DELETE') { state.flightTypes = state.flightTypes.filter(item => item.id !== id); return route.fulfill({ status: 204 }) }
      if (path.endsWith('/thresholds')) existing.thresholds = body.thresholds.map((item: { competenceId: number; value: string }) => threshold(item.competenceId, item.value))
      else { if (body.isMain) state.flightTypes.forEach(item => { item.isMain = item.id === id }); if (body.name !== undefined) existing.name = body.name }
      return json(route, existing)
    }
    if (path === '/api/commander/pilots/compatibility') {
      const selected = state.flightTypes.find(item => item.id === Number(url.searchParams.get('flightTypeId')))
      if (!selected) return json(route, { detail: 'Training type not found' }, 404)
      const pilot = (id: string) => ({ ...user(id), hasCompletedTraining: true })
      const result: PilotCompatibilityResponse = { firstPilot: pilot(url.searchParams.get('firstPilotId')!), secondPilot: pilot(url.searchParams.get('secondPilotId')!), flightType: selected, asOfDate: url.searchParams.get('asOfDate'), items: competences.map(competence => {
        const threshold = selected.thresholds.find(item => item.competenceId === competence.id)
        return { competenceId: competence.id, competenceCode: competence.code, competenceName: competence.name, orderIndex: competence.orderIndex, compatible: Boolean(threshold && 6 >= Number(threshold.value)), thresholdConfigured: Boolean(threshold), requiredSum: threshold?.value ?? null, actualSum: 6, firstPilotValue: 3, secondPilotValue: 3 }
      }) }
      return json(route, result)
    }
    if (path === '/api/commander/training-sessions' || path === '/api/commander/scenarios') return json(route, { total: 0, limit: 20, offset: 0, items: [] })
    return json(route, { detail: `Unmocked endpoint: ${method} ${path}` }, 501)
  })
  return state
}
export async function login(page: Page, path = '/pilots') {
  await page.goto(path)
  await page.getByLabel('Login', { exact: true }).fill('admin')
  await page.getByLabel('Password', { exact: true }).fill('test-password')
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
}
export async function persistSession(page: Page, savedUser = user()) {
  await page.addInitScript(({ tokenPair, savedUser }) => localStorage.setItem('session-store', JSON.stringify({ state: { tokens: tokenPair, user: savedUser, privileges: savedUser.privileges }, version: 0 })), { tokenPair, savedUser })
}
