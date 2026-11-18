export type ExerciseElementPayload = {
  elementId: number
  orderIndex: number
  details: string | null
  startingHeight: number | null
  endingHeight: number | null
  profileType: 'FLAT' | 'UP' | 'DOWN' | 'LINKED'
}

export type ExerciseParamPayload = {
  intensity: string | null
  zfwT: string | null
  guidance: string | null
  originalTl: TakeoffLandingPayload | null
  destinationTl: TakeoffLandingPayload | null
}

export type TakeoffLandingPayload = {
  airportName: string | null
  timeOfDay: string | null
  runway: string | null
  brakingAction: string | null
  specialWx: string | null
  windDir: string | null
  windSpeed: string | null
  windGust: string | null
  visibilityValue: string | null
  cloudsAmount: string | null
  cloudsCeilingFt: string | null
  rvrH: string | null
  rvrV: string | null
  temperatureC: string | null
  qnhHpa: string | null
  fuel: string | null
  cgPercent: string | null
  thrustSetting: string | null
  flapsSetting: string | null
  v2Speed: string | null
  vrSpeed: string | null
  v1Speed: string | null
  sid: string | null
  squawkCode: string | null
  frequency: string | null
  climb: string | null
}

export type ExerciseSnapshot = {
  id: number
  clientUid: string | null
  moduleId: number
  orderIndex: number
  durationMinutes: number | null
  crewMemberNumber: number | null
  competenceIds: number[]
  elements: ExerciseElementPayload[]
  params: ExerciseParamPayload | null
}

export type ModuleSnapshot = {
  id: number
  clientUid: string | null
  scenarioId: number
  orderIndex: number
  dayIndex?: number | null
  dayStart: boolean
  durationMinutes: number | null
  contentSubcolumnId: number | null
  exercises: ExerciseSnapshot[]
}

export type ScenarioSnapshot = {
  modules: ModuleSnapshot[]
}
