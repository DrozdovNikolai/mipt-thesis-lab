import type { ScenarioSnapshot } from './scenarioSnapshot'

export type ScenarioRevisionKind = 'AUTO' | 'MANUAL'

export type ScenarioRevisionListItem = {
  id: number
  scenarioId: number
  createdBy: number | null
  kind: ScenarioRevisionKind
  label: string | null
  signature: string
  clientEntryId: string | null
  clientCreatedAtMs: number | null
  createdAt: string
}

export type ScenarioRevisionDetail = ScenarioRevisionListItem & {
  snapshot: ScenarioSnapshot
}
