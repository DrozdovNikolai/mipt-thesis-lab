// Fixtures extracted from the verified React baseline: pilot-profile-route.spec.ts
// Source SHA-256: be70bfa1a3a2cad843292dd9a6848cf02e77195328e4c2b46e4529b4b7c60845
import type { Page } from '@playwright/test'

const makeMockUser = () => ({
  id: 'commander-user',
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
  aircraftIds: [1],
  aircraftCodes: ['A320'],
})

export async function installProfileFixtures(page: Page) {

  await page.route('**/api/commander/flight-types', route => route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }))

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

  await page.route('**/api/commander/training-sessions**', async (route) => {
    const url = new URL(route.request().url())
    const detailMatch = url.pathname.match(/\/api\/commander\/training-sessions\/(\d+)$/)

    if (!detailMatch) {
      await route.fulfill({
        status: 404,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Not found' }),
      })
      return
    }

    const trainingSessionId = Number(detailMatch[1])

    if (trainingSessionId !== 202) {
      await route.fulfill({
        status: 404,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Not found' }),
      })
      return
    }

    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        session: {
          id: 202,
          title: 'Scenario Bravo',
          completedAt: '2025-01-05T10:00:00Z',
          instructorId: 'instructor-1',
          instructorFirstName: 'Ian',
          instructorLastName: 'Instructor',
          cm1Id: 'pilot-2',
          cm1FirstName: 'Bob',
          cm1LastName: 'Bravo',
          cm2Id: 'pilot-1',
          cm2FirstName: 'Alice',
          cm2LastName: 'Alpha',
          aircraftId: 2,
          previousDays: [],
          scenarioId: 20,
          scenarioDayModuleId: 2001,
          dayIndex: 1,
          daysCount: 1,
          aircraftCode: 'A321',
          notes: 'Pilot profile drilldown note.',
        },
        modules: [
          {
            id: 301,
            clientUid: 'module-301',
            orderIndex: 0,
            durationMinutes: 90,
            contentSubcolumnId: 41,
            contentSubcolumnName: 'Handling',
            exercises: [
              {
                id: 401,
                clientUid: 'exercise-401',
                moduleId: 301,
                orderIndex: 0,
                durationMinutes: 22,
                crewMemberNumber: 2,
                params: {
                  id: 501,
                  intensity: 'MEDIUM',
                  zfwT: '60.4',
                  guidance: 'Manage the abnormal and maintain situational awareness.',
                  originalTl: null,
                  destinationTl: null,
                },
                competences: [{ id: 1, code: 'COM', name: 'Communication', orderIndex: 0 }],
                elements: [
                  {
                    id: 701,
                    elementId: 801,
                    elementName: 'Go Around',
                    elementSeverity: 5,
                    orderIndex: 0,
                    details: 'Late windshear escape',
                    startingHeight: 1200,
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
            trainingRole: 'cm2',
            pilotId: 'pilot-1',
            pilotFirstName: 'Alice',
            pilotLastName: 'Alpha',
            summary: 'Alice managed workload well in the final segment.',
            result: true,
            signedAt: '2025-01-05T10:30:00Z',
            finalReports: [
              {
                id: 1001,
                competenceId: 1,
                competenceCode: 'COM',
                competenceName: 'Communication',
                orderIndex: 0,
                gradeCode: 'EDGE',
                gradeLabel: 'Edge',
                gradeScoreNumeric: '4.1',
                gradeColorHex: '#0088AA',
              },
            ],
            exerciseReports: [
              {
                exerciseId: 401,
                remarkCount: 1,
                positiveRemarkCount: 1,
                negativeRemarkCount: 0,
                remarks: [
                  {
                    id: 1101,
                    exerciseId: 401,
                    timestamp: '2025-01-05T10:18:00Z',
                    exerciseOffsetSec: 25,
                    exerciseSessionKey: 'exercise-401',
                    competenceId: 1,
                    competenceCode: 'COM',
                    competenceName: 'Communication',
                    behaviouralIndicatorId: 1,
                    behaviouralIndicatorCode: 'COM-BI-1',
                    behaviouralIndicatorName: 'Callouts',
                    isPositive: true,
                    hashtag: 'briefing',
                    comment: 'Clear PM coordination during the go-around.',
                  },
                ],
              },
            ],
            aiReviews: [],
          },
        ],
      }),
    })
  })

  await page.route('**/api/commander/pilots**', async (route) => {
    const url = new URL(route.request().url())
    const pathname = url.pathname

    if (pathname.endsWith('/training-summary')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          pilot: {
            id: 'pilot-1',
            fullName: 'Alice Alpha',
            firstName: 'Alice',
            lastName: 'Alpha',
            positionId: 11,
            position: 'Captain',
            aircraftIds: [1, 2],
            aircraftCodes: ['A320', 'A321'],
            rating: '4.1',
            phone: '+1-555-0100',
            email: 'alice.alpha@example.com',
          },
          latestCompletedTraining: {
            trainingSessionId: 202,
            title: 'Scenario Bravo',
            completedAt: '2025-01-05T10:00:00Z',
            trainingRole: 'cm2',
            initialCrewSlot: 'CM2',
            finalCrewSlot: 'CM2',
            swapCount: 2,
            pfDurationMs: 45_000,
            pmDurationMs: 75_000,
            roleProjectionSource: 'ACTUAL_TIMELINE',
            grades: [
              {
                competenceId: 1,
                competenceCode: 'COM',
                competenceName: 'Communication',
                orderIndex: 1,
                gradeCode: 'EDGE',
                gradeLabel: 'Edge',
                gradeScoreNumeric: '4.1',
                gradeColorHex: '#0088AA',
              },
              {
                competenceId: 2,
                competenceCode: 'PRO',
                competenceName: 'Procedures',
                orderIndex: 2,
                gradeCode: 'HIGH',
                gradeLabel: 'High',
                gradeScoreNumeric: '5.0',
                gradeColorHex: '#00AA00',
              },
            ],
          },
          competenceHistories: [
            {
              competenceId: 1,
              competenceCode: 'COM',
              competenceName: 'Communication',
              orderIndex: 1,
              history: [
                {
                  trainingSessionId: 202,
                  trainingSessionTitle: 'Scenario Bravo',
                  completedAt: '2025-01-05T10:00:00Z',
                  gradeCode: 'EDGE',
                  gradeLabel: 'Edge',
                  gradeScoreNumeric: '4.1',
                  gradeColorHex: '#0088AA',
                },
                {
                  trainingSessionId: 201,
                  trainingSessionTitle: 'Scenario Alpha-DAY 2',
                  completedAt: '2025-01-03T10:00:00Z',
                  gradeCode: 'HIGH',
                  gradeLabel: 'High',
                  gradeScoreNumeric: '5.0',
                  gradeColorHex: '#00AA00',
                },
              ],
            },
          ],
          positionAverageGrades: [],
          completedTrainingSessions: [
            {
              id: 202,
              title: 'Scenario Bravo',
              completedAt: '2025-01-05T10:00:00Z',
              instructorId: 'instructor-1',
              instructorFirstName: 'Ian',
              instructorLastName: 'Instructor',
              cm1Id: 'pilot-2',
              cm1FirstName: 'Bob',
              cm1LastName: 'Bravo',
              cm2Id: 'pilot-1',
              cm2FirstName: 'Alice',
              cm2LastName: 'Alpha',
              aircraftId: 2,
              previousDays: [],
              trainingRole: 'cm2',
              initialCrewSlot: 'CM2',
              finalCrewSlot: 'CM2',
              swapCount: 2,
              pfDurationMs: 45_000,
              pmDurationMs: 75_000,
              roleProjectionSource: 'ACTUAL_TIMELINE',
            },
            {
              id: 201,
              title: 'Scenario Alpha-DAY 2',
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
              previousDays: [{ id: 101, title: 'Scenario Alpha-DAY 1' }],
              trainingRole: 'cm1',
            },
          ],
        }),
      })
      return
    }

    if (pathname.endsWith('/pilot-1')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          id: 'pilot-1',
          fullName: 'Alice Alpha',
          firstName: 'Alice',
          lastName: 'Alpha',
          positionId: 11,
          position: 'Captain',
          aircraftIds: [1, 2],
          aircraftCodes: ['A320', 'A321'],
          rating: '4.1',
          phone: '+1-555-0100',
          email: 'alice.alpha@example.com',
        }),
      })
      return
    }

    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        total: 1,
        limit: 20,
        offset: 0,
        items: [
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
            phone: '+1-555-0100',
            photoUrl: null,
            signatureUrl: null,
            airlineId: 1,
            roles: [],
            privileges: ['pilots:read'],
            aircraftIds: [1, 2],
            aircraftCodes: ['A320', 'A321'],
            rating: '4.1',
          },
        ],
      }),
    })
  })

  
}
