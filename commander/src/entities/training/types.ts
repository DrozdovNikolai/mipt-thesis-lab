import type {
  BehaviouralIndicatorRead,
  CompetenceRead,
  ModuleRead,
  ScenarioContentSetRead,
  ScenarioRead,
} from './types.generated'
import type { ExerciseParamPayload } from './scenarioSnapshot'

export type Scenario = ScenarioRead
export type Module = ModuleRead
export type Competence = CompetenceRead
export type BehaviouralIndicator = BehaviouralIndicatorRead

export type ScenarioSummaryItem = {
  id: number
  title: string
  status: string
  aircraftId: number
  aircraftCode?: string | null
  engines: string | null
  updatedAt: string
  createdAt: string
  modulesCount: number
  daysCount: number
  durationTotalMinutes: number
  contentSetId?: number | null
  setLabelId?: number | null
}

export type ScenarioSummaryPage = {
  total: number
  limit: number
  offset: number
  items: ScenarioSummaryItem[]
}

export type ContentSetSummaryItem = ScenarioContentSetRead & {
  scenariosCount: number
  subcolumnsCount: number
  foldersCount: number
  requirementsCount: number
}

export type ContentSetSummaryPage = {
  total: number
  limit: number
  offset: number
  items: ContentSetSummaryItem[]
}

export type Airline = {
  id: number
  code: string | null
  name: string
  active: boolean
  usersStoredInLocalDb: boolean
  createdAt: string
  updatedAt: string
}

export type AirlineGradingScaleValue = {
  id: number
  code: string
  label: string
  scoreNumeric: string
  gradeWeight: string
  orderIndex: number
  colorHex: string | null
  isPass: boolean
}

export type AirlineGradingScale = {
  airlineId: number
  schemeId: number
  schemeName: string
  schemeVersion: number
  values: AirlineGradingScaleValue[]
}

export type AirlineGradingScaleValueInput = {
  code: string
  label: string
  scoreNumeric: string | number
  gradeWeight: string | number
  orderIndex: number
  colorHex?: string | null
  isPass: boolean
}

export type ReplaceAirlineGradingScalePayload = {
  schemeName: string
  values: AirlineGradingScaleValueInput[]
}

export type AircraftAirline = {
  id: number
  airlineId: number
  code: string
  name: string | null
  active: boolean
  colorHex: string
  createdAt: string
  updatedAt: string
}

export type Element = {
  id: number
  name: string
  defaultDurationMinutes: number | null
  severity: number | null
  colorHex?: string | null
  defaultFolderId?: number | null
}

export type ElementBlock = {
  id: number
  params:
    | (ExerciseParamPayload & { durationMinutes: number | null; crewMemberNumber: number | null })
    | null
  colorHex?: string | null
  competenceIds: number[]
  elements: Array<{
    id: number
    elementId: number
    orderIndex: number
    details: string | null
    startingHeight: number | null
    endingHeight: number | null
    profileType: 'FLAT' | 'UP' | 'DOWN' | 'LINKED'
  }>
}

export type TaskFolder = {
  id: number
  name: string
  parentId: number | null
  colorHex: string | null
  orderIndex: number | null
  aircraftId: number | null
  aircraftCode?: string | null
  airlineId: number | null
}

export type FolderItem = {
  id: number
  folderId: number
  elementId: number | null
  blockId: number | null
  orderIndex: number | null
}

// Generated types from backend schemas (ScenarioRead/ModuleRead)
// If backend changes, update types.generated accordingly.
