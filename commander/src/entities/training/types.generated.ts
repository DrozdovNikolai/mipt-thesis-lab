// Minimal generated types aligned with backend training schemas
export type CompetenceRead = {
  id: number
  code: string
  name: string
  description: string | null
  orderIndex: number
  createdAt: string
  updatedAt: string
}

export type BehaviouralIndicatorRead = {
  id: number
  code: string
  shortName: string | null
  name: string
  orderIndex: number
  createdAt: string
  updatedAt: string
}

export type ScenarioRead = {
  id: number
  airlineId: number
  aircraftId: number
  aircraftCode?: string | null
  contentVersion: number
  code: string | null
  title: string
  engines: string | null
  comments: string | null
  status: string | null
  publishedAt: string | null
  validUntil: string | null
  createdAt: string
  updatedAt: string
  modules: ModuleRead[]
}

export type ModuleRead = {
  id: number
  clientUid: string
  scenarioId: number
  orderIndex: number
  dayIndex?: number
  dayStart: boolean
  durationMinutes: number | null
  contentSubcolumnId: number | null
  contentSubcolumn?: ScenarioContentSubColumnRead | null
  createdAt: string
  updatedAt: string
  exercises: ExerciseRead[]
}

export type ExerciseRead = {
  id: number
  clientUid: string
  moduleId: number
  orderIndex: number
  durationMinutes: number | null
  crewMemberNumber: number | null
  createdAt: string
  updatedAt: string
  elements: ExerciseElementRead[]
  competences: CompetenceRead[]
  params: ExerciseParamRead | null
}

export type ExerciseElementRead = {
  id: number
  elementId: number
  orderIndex: number
  details: string | null
  startingHeight?: number | null
  endingHeight?: number | null
  profileType?: 'FLAT' | 'UP' | 'DOWN' | 'LINKED'
}

export type ExerciseParamRead = {
  id: number
  intensity: string | null
  zfwT: string | null
  guidance: string | null
  originalTl: TakeoffLandingRead | null
  destinationTl: TakeoffLandingRead | null
}

export type TakeoffLandingRead = {
  id: number
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

export type ElementRead = {
  id: number
  name: string
  defaultDurationMinutes: number | null
  severity: number | null
  colorHex?: string | null
}

// Scenario content sets (matrix)
export type ScenarioLiteRead = {
  id: number
  aircraftId: number
  aircraftCode?: string | null
  code: string | null
  title: string
  status: string
}

export type ScenarioContentSetRead = {
  id: number
  airlineId: number
  aircraftId: number
  aircraftCode?: string | null
  name: string
  validFrom: string | null
  validTo: string | null
  createdBy: number | null
  updatedBy: number | null
  createdAt: string
  updatedAt: string
}

export type ScenarioContentSetLabelScenarioRead = {
  id: number
  labelId: number
  scenarioId: number
  createdAt: string
  scenario: ScenarioLiteRead | null
}

export type ScenarioContentSetLabelRead = {
  id: number
  contentSetId: number
  orderIndex: number
  label: string | null
  createdAt: string
  updatedAt: string
  scenarios: ScenarioContentSetLabelScenarioRead[]
}

export type ScenarioContentFolderRead = {
  id: number
  contentSetId: number
  parentId: number | null
  name: string
  orderIndex: number
  createdAt: string
  updatedAt: string
}

export type ScenarioContentRequirementElementRead = {
  id: number
  requirementId: number
  elementId: number
  orderIndex: number
  element: ElementRead
  createdAt: string
  updatedAt: string
}

export type ScenarioContentRequirementRead = {
  id: number
  contentSetId: number
  folderId: number
  topicName: string
  orderIndex: number
  elements: ScenarioContentRequirementElementRead[]
  createdAt: string
  updatedAt: string
}

export type ScenarioContentSubColumnRead = {
  id: number
  contentSetId: number
  name: string
  orderIndex: number
  createdAt: string
  updatedAt: string
}

export type ScenarioContentCellRead = {
  id: number
  contentSetId: number
  requirementId: number
  setLabelId: number
  subcolumnId: number
  value: boolean
  createdAt: string
  updatedAt: string
}

export type ScenarioContentSetMatrix = {
  contentSet: ScenarioContentSetRead
  labels: ScenarioContentSetLabelRead[]
  folders: ScenarioContentFolderRead[]
  requirements: ScenarioContentRequirementRead[]
  subcolumns: ScenarioContentSubColumnRead[]
  cells: ScenarioContentCellRead[]
}

export type ScenarioContentSetSubcolumns = {
  id: number
  name: string
  aircraftId: number
  aircraftCode?: string | null
  subcolumns: ScenarioContentSubColumnRead[]
}
