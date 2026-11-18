// Fixtures extracted from the verified React baseline: training-sessions-route.spec.ts
// Source SHA-256: 89c5423dc1235bc4a099e1753ea3ae5ae29327220454768dcc1d716454f61524
import type { Page } from '@playwright/test'

const makeMockUser = () => ({
  id: '1',
  login: 'commander',
  email: 'commander@example.com',
  isActive: true,
  mustChangePassword: false,
  createdAt: '2026-01-01T00:00:00.000Z',
  firstName: 'Commander',
  lastName: 'User',
  position: 'Captain',
  licenseNumber: null,
  phone: null,
  photoUrl: null,
  signatureUrl: null,
  airlineId: 1,
  roles: [],
  privileges: ['pilots:read'],
  aircraftIds: [1, 2],
  aircraftCodes: ['A320', 'A321'],
})

const pilotItems = [
  {
    id: 'instructor-1',
    login: 'ian.instructor',
    email: 'ian.instructor@example.com',
    isActive: true,
    mustChangePassword: false,
    createdAt: '2026-01-01T00:00:00.000Z',
    firstName: 'Ian',
    lastName: 'Instructor',
    position: 'Instructor',
    licenseNumber: null,
    phone: null,
    photoUrl: null,
    signatureUrl: null,
    airlineId: 1,
    roles: [],
    privileges: ['pilots:read'],
    aircraftIds: [1],
    aircraftCodes: ['A320'],
  },
  {
    id: 'pilot-1',
    login: 'alice.alpha',
    email: 'alice.alpha@example.com',
    isActive: true,
    mustChangePassword: false,
    createdAt: '2026-01-01T00:00:00.000Z',
    firstName: 'Alice',
    lastName: 'Alpha',
    position: 'Captain',
    licenseNumber: null,
    phone: null,
    photoUrl: null,
    signatureUrl: null,
    airlineId: 1,
    roles: [],
    privileges: ['pilots:read'],
    aircraftIds: [1, 2],
    aircraftCodes: ['A320', 'A321'],
  },
  {
    id: 'pilot-2',
    login: 'bob.bravo',
    email: 'bob.bravo@example.com',
    isActive: true,
    mustChangePassword: false,
    createdAt: '2026-01-01T00:00:00.000Z',
    firstName: 'Bob',
    lastName: 'Bravo',
    position: 'First Officer',
    licenseNumber: null,
    phone: null,
    photoUrl: null,
    signatureUrl: null,
    airlineId: 1,
    roles: [],
    privileges: ['pilots:read'],
    aircraftIds: [1],
    aircraftCodes: ['A320'],
  },
]

const allSessions = [
  {
    id: 102,
    title: 'Scenario Bravo',
    dayTitle: null,
    completedAt: '2025-01-05T10:00:00Z',
    instructorId: 'instructor-1',
    instructorFirstName: 'Ian',
    instructorLastName: 'Instructor',
    cm1Id: 'pilot-1',
    cm1FirstName: 'Alice',
    cm1LastName: 'Alpha',
    cm2Id: 'pilot-2',
    cm2FirstName: 'Bob',
    cm2LastName: 'Bravo',
    aircraftId: 2,
    previousDays: [],
  },
  {
    id: 101,
    title: 'Scenario Alpha',
    dayTitle: 'Scenario Alpha-DAY 3',
    completedAt: '2025-01-03T10:00:00Z',
    instructorId: 'instructor-1',
    instructorFirstName: 'Ian',
    instructorLastName: 'Instructor',
    cm1Id: 'pilot-1',
    cm1FirstName: 'Alice',
    cm1LastName: 'Alpha',
    cm2Id: 'pilot-2',
    cm2FirstName: 'Bob',
    cm2LastName: 'Bravo',
    aircraftId: 1,
    previousDays: [
      { id: 12, title: 'Scenario Alpha-DAY 2' },
      { id: 11, title: 'Scenario Alpha-DAY 1' },
    ],
  },
]

export const trainingSessionDetailsById = {
  102: {
    session: {
      id: 102,
      title: 'Scenario Bravo',
      completedAt: '2025-01-05T10:00:00Z',
      instructorId: 'instructor-1',
      instructorFirstName: 'Ian',
      instructorLastName: 'Instructor',
      cm1Id: 'pilot-1',
      cm1FirstName: 'Alice',
      cm1LastName: 'Alpha',
      cm2Id: 'pilot-2',
      cm2FirstName: 'Bob',
      cm2LastName: 'Bravo',
      aircraftId: 2,
      previousDays: [],
      scenarioId: 20,
      scenarioDayModuleId: 2001,
      dayIndex: 1,
      daysCount: 1,
      aircraftCode: 'A321',
      notes: 'Debrief note for Scenario Bravo.',
    },
    crewRuntime: {
      projectionSource: 'ACTUAL_TIMELINE',
      sealed: true,
      initialEventId: '00000000-0000-7000-8000-000000000001',
      currentEventId: '00000000-0000-7000-8000-000000000002',
      initialCm1AssessmentId: 901,
      initialCm2AssessmentId: 902,
      finalCm1AssessmentId: 902,
      finalCm2AssessmentId: 901,
      swapCount: 1,
      latestSwap: {
        eventId: '00000000-0000-7000-8000-000000000002',
        serverRevision: 1,
        acceptedAt: '2025-01-05T09:45:30Z',
        eventScope: 'EXERCISE_RUN',
        trainingSessionExerciseId: 401,
        exerciseSessionKey: '00000000-0000-7000-8000-000000000101',
        exerciseOffsetMs: 30_000,
        cm1AssessmentIdBefore: 901,
        cm2AssessmentIdBefore: 902,
        cm1AssessmentIdAfter: 902,
        cm2AssessmentIdAfter: 901,
      },
    },
    participants: [
      {
        assessmentId: 901,
        pilotId: 'pilot-1',
        firstName: 'Alice',
        lastName: 'Alpha',
        photoUrl: null,
        initialCrewSlot: 'CM1',
        finalCrewSlot: 'CM2',
        pfDurationMs: 30_000,
        pmDurationMs: 60_000,
      },
      {
        assessmentId: 902,
        pilotId: 'pilot-2',
        firstName: 'Bob',
        lastName: 'Bravo',
        photoUrl: null,
        initialCrewSlot: 'CM2',
        finalCrewSlot: 'CM1',
        pfDurationMs: 60_000,
        pmDurationMs: 30_000,
      },
    ],
    modules: [
      {
        id: 301,
        clientUid: 'module-301',
        orderIndex: 0,
        durationMinutes: 120,
        contentSubcolumnId: 41,
        contentSubcolumnName: 'Pre-flight briefing',
        exercises: [
          {
            id: 401,
            clientUid: 'exercise-401',
            moduleId: 301,
            orderIndex: 0,
            durationMinutes: 18,
            crewMemberNumber: 1,
            resolvedForAssessmentId: null,
            runs: [
              {
                exerciseSessionKey: '00000000-0000-7000-8000-000000000101',
                runIndex: 1,
                status: 'COMPLETED',
                activeDurationMs: 90_000,
              },
            ],
            params: {
              id: 501,
              intensity: 'HIGH',
              zfwT: '61.2',
              guidance: 'Brief abnormal departure and stabilize the first segment.',
              originalTl: {
                id: 601,
                airportName: 'UUEE',
                timeOfDay: 'DAY',
                runway: '24R',
                brakingAction: null,
                specialWx: null,
                windDir: '240',
                windSpeed: '12',
                windGust: null,
                visibilityValue: '9999',
                cloudsAmount: null,
                cloudsCeilingFt: null,
                rvrH: null,
                rvrV: null,
                temperatureC: '10',
                qnhHpa: '1015',
                fuel: '8.2',
                cgPercent: '24',
                thrustSetting: 'TOGA',
                flapsSetting: '1+F',
                v2Speed: '145',
                vrSpeed: '142',
                v1Speed: '139',
                sid: 'BERVO 1D',
                squawkCode: null,
                frequency: '121.9',
                climb: 'SID',
              },
              destinationTl: {
                id: 602,
                airportName: 'ULLI',
                timeOfDay: 'DAY',
                runway: '10R',
                brakingAction: 'GOOD',
                specialWx: null,
                windDir: '090',
                windSpeed: '08',
                windGust: null,
                visibilityValue: '8000',
                cloudsAmount: 'SCT',
                cloudsCeilingFt: '1800',
                rvrH: null,
                rvrV: null,
                temperatureC: '7',
                qnhHpa: '1012',
                fuel: '5.4',
                cgPercent: null,
                thrustSetting: null,
                flapsSetting: null,
                v2Speed: null,
                vrSpeed: null,
                v1Speed: null,
                sid: null,
                squawkCode: null,
                frequency: null,
                climb: null,
              },
            },
            competences: [
              { id: 1, code: 'COM', name: 'Communication', orderIndex: 0 },
              { id: 2, code: 'FPM', name: 'Flight path management', orderIndex: 1 },
            ],
            elements: [
              {
                id: 701,
                elementId: 801,
                elementName: 'Engine Fire',
                elementSeverity: 8,
                orderIndex: 0,
                details: 'Fire after V1',
                startingHeight: 0,
                endingHeight: 3000,
                profileType: 'UP',
              },
            ],
          },
        ],
      },
    ],
    assessments: [
      {
        id: 901,
        trainingRole: 'cm1',
        pilotId: 'pilot-1',
        pilotFirstName: 'Alice',
        pilotLastName: 'Alpha',
        summary: 'Strong callouts and stable task sharing.',
        result: true,
        signedAt: '2025-01-05T10:45:00Z',
        finalReports: [
          {
            id: 1001,
            competenceId: 1,
            competenceCode: 'COM',
            competenceName: 'Communication',
            orderIndex: 0,
            gradeCode: '5',
            gradeLabel: 'Excellent',
            gradeScoreNumeric: '5.0',
            gradeColorHex: '#00AA00',
          },
        ],
        exerciseReports: [
          {
            exerciseId: 401,
            remarkCount: 2,
            positiveRemarkCount: 1,
            negativeRemarkCount: 1,
            remarks: [
              {
                id: 1101,
                exerciseId: 401,
                timestamp: '2025-01-05T10:12:00Z',
                exerciseOffsetSec: 10,
                exerciseOffsetMs: 10_000,
                exerciseSessionKey: '00000000-0000-7000-8000-000000000101',
                assignmentEventIdAtObservation: '00000000-0000-7000-8000-000000000001',
                crewSlotAtObservation: 'CM1',
                dutyAtObservation: 'PF',
                roleProjectionSource: 'TIMELINE',
                competenceId: 1,
                competenceCode: 'COM',
                competenceName: 'Communication',
                behaviouralIndicatorId: 1,
                behaviouralIndicatorCode: 'COM-BI-1',
                behaviouralIndicatorName: 'Callouts',
                isPositive: true,
                hashtag: 'callout',
                comment: 'Strong callout discipline',
              },
              {
                id: 1102,
                exerciseId: 401,
                timestamp: '2025-01-05T10:13:00Z',
                exerciseOffsetSec: 34,
                exerciseOffsetMs: 34_000,
                exerciseSessionKey: '00000000-0000-7000-8000-000000000101',
                assignmentEventIdAtObservation: '00000000-0000-7000-8000-000000000002',
                crewSlotAtObservation: 'CM2',
                dutyAtObservation: 'PM',
                roleProjectionSource: 'TIMELINE',
                competenceId: 2,
                competenceCode: 'FPM',
                competenceName: 'Flight path management',
                behaviouralIndicatorId: 2,
                behaviouralIndicatorCode: 'FPM-BI-1',
                behaviouralIndicatorName: 'Pitch control',
                isPositive: false,
                hashtag: 'pitch',
                comment: 'Pitch correction was delayed after the failure.',
              },
            ],
          },
        ],
        aiReviews: [
          {
            id: 1201,
            competenceId: 1,
            competenceCode: 'COM',
            competenceName: 'Communication',
            text: 'AI review for communication competence',
          },
        ],
      },
      {
        id: 902,
        trainingRole: 'cm2',
        pilotId: 'pilot-2',
        pilotFirstName: 'Bob',
        pilotLastName: 'Bravo',
        summary: 'Monitoring duties were acceptable.',
        result: false,
        signedAt: '2025-01-05T10:46:00Z',
        finalReports: [],
        exerciseReports: [],
        aiReviews: [],
      },
    ],
  },
}

export async function installTrainingSessionsFixtures(page: Page) {

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
      body: JSON.stringify(makeMockUser()),
    })
  })

  await page.route('**/api/commander/aircraft**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([
        { id: 1, code: 'A320', name: 'Airbus A320', active: true, airlineId: 1, createdAt: '2026-01-01T00:00:00Z', updatedAt: '2026-01-01T00:00:00Z' },
        { id: 2, code: 'A321', name: 'Airbus A321', active: true, airlineId: 1, createdAt: '2026-01-01T00:00:00Z', updatedAt: '2026-01-01T00:00:00Z' },
      ]),
    })
  })

  await page.route('**/api/commander/scenarios**', async (route) => {
    const url = new URL(route.request().url())
    const aircraftId = url.searchParams.get('aircraftId')
    const q = url.searchParams.get('q')?.toLowerCase() ?? ''

    const items = [
      { id: 10, title: 'Scenario Alpha', status: 'PUBLISHED', aircraftId: 1, aircraftCode: 'A320' },
      { id: 20, title: 'Scenario Bravo', status: 'PUBLISHED', aircraftId: 2, aircraftCode: 'A321' },
    ].filter((item) => {
      if (aircraftId && String(item.aircraftId) !== aircraftId) return false
      if (q && !item.title.toLowerCase().includes(q)) return false
      return true
    })

    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        total: items.length,
        limit: 10,
        offset: 0,
        items,
      }),
    })
  })

  await page.route('**/api/commander/pilots**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        total: pilotItems.length,
        limit: 10,
        offset: 0,
        items: pilotItems,
      }),
    })
  })

  await page.route('**/api/commander/training-sessions**', async (route) => {
    const url = new URL(route.request().url())
    const detailMatch = url.pathname.match(/\/api\/commander\/training-sessions\/(\d+)$/)

    if (detailMatch) {
      const detail = trainingSessionDetailsById[Number(detailMatch[1]) as keyof typeof trainingSessionDetailsById]

      await route.fulfill({
        status: detail ? 200 : 404,
        contentType: 'application/json',
        body: JSON.stringify(detail ?? { detail: 'Not found' }),
      })
      return
    }

    const scenarioId = url.searchParams.get('scenarioId')
    const items = scenarioId === '20' ? allSessions.filter((item) => item.id === 102) : allSessions

    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        total: items.length,
        limit: 20,
        offset: 0,
        items,
      }),
    })
  })

  
}
