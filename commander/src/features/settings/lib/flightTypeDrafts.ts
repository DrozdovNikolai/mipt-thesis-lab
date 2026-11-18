import type {
  CommanderFlightType,
  CommanderFlightTypeThreshold,
  CommanderFlightTypeThresholdInput,
  CommanderFlightTypeThresholdsReplacePayload,
} from '@/entities/commander/types'
import type { Competence } from '@/entities/training/types'
import {
  FLIGHT_TYPE_THRESHOLD_MAX_DECIMAL_DIGITS,
  FLIGHT_TYPE_THRESHOLD_MAX_VALUE,
  isFlightTypeThresholdInputValid,
} from '@/features/settings/lib/settingsConstraints'

export type FlightTypeDraft = {
  name: string
  thresholds: Record<number, string>
}

const collectThresholdIds = (
  flightType: CommanderFlightType,
  draftThresholds: Record<number, string>,
  competences: Competence[],
) => {
  const ids = new Set<number>()

  for (const competence of competences) {
    ids.add(competence.id)
  }

  for (const threshold of flightType.thresholds) {
    ids.add(threshold.competenceId)
  }

  for (const rawCompetenceId of Object.keys(draftThresholds)) {
    const competenceId = Number(rawCompetenceId)
    if (Number.isFinite(competenceId)) {
      ids.add(competenceId)
    }
  }

  return ids
}

export const normalizeFlightTypeName = (value: string) => value.replace(/\s+/g, ' ').trim()

export const formatThresholdValue = (value: string | number | null | undefined) => {
  if (value === null || value === undefined || value === '') return ''

  const numericValue = Number(value)
  if (Number.isFinite(numericValue)) {
    return numericValue.toString()
  }

  return String(value).trim()
}

export const buildThresholdDraft = (thresholds: CommanderFlightTypeThreshold[]) =>
  Object.fromEntries(
    thresholds.map((threshold) => [threshold.competenceId, formatThresholdValue(threshold.value)]),
  )

export const createFlightTypeDraft = (flightType: CommanderFlightType): FlightTypeDraft => ({
  name: flightType.name,
  thresholds: buildThresholdDraft(flightType.thresholds),
})

export const areThresholdDraftsEqual = (
  flightType: CommanderFlightType,
  draftThresholds: Record<number, string>,
  competences: Competence[],
) => {
  const serverThresholds = buildThresholdDraft(flightType.thresholds)

  for (const competenceId of collectThresholdIds(flightType, draftThresholds, competences)) {
    if (
      formatThresholdValue(serverThresholds[competenceId] ?? '') !==
      formatThresholdValue(draftThresholds[competenceId] ?? '')
    ) {
      return false
    }
  }

  return true
}

export const pruneFlightTypeDraft = (
  flightType: CommanderFlightType,
  draft: FlightTypeDraft,
  competences: Competence[],
): FlightTypeDraft | null => {
  const isNameDirty = normalizeFlightTypeName(draft.name) !== flightType.name
  const areThresholdsDirty = !areThresholdDraftsEqual(flightType, draft.thresholds, competences)

  if (!isNameDirty && !areThresholdsDirty) {
    return null
  }

  return draft
}

export const countConfiguredThresholds = (
  competences: Competence[],
  thresholdValues: Record<number, string>,
) =>
  competences.reduce(
    (total, competence) =>
      formatThresholdValue(thresholdValues[competence.id] ?? '') ? total + 1 : total,
    0,
  )

export const buildThresholdsReplacePayload = (
  competences: Competence[],
  thresholdValues: Record<number, string>,
): {
  payload: CommanderFlightTypeThresholdsReplacePayload | null
  validationMessage: string | null
} => {
  const thresholds: CommanderFlightTypeThresholdInput[] = []
  const invalidCompetenceLabels: string[] = []

  for (const competence of competences) {
    const rawValue = String(thresholdValues[competence.id] ?? '').trim()
    if (!rawValue) continue

    if (!isFlightTypeThresholdInputValid(rawValue)) {
      invalidCompetenceLabels.push(competence.code || competence.name)
      continue
    }

    const numericValue = Number(rawValue)
    if (!Number.isFinite(numericValue) || numericValue < 0) {
      invalidCompetenceLabels.push(competence.code || competence.name)
      continue
    }

    thresholds.push({
      competenceId: competence.id,
      value: numericValue.toString(),
    })
  }

  if (invalidCompetenceLabels.length > 0) {
    const preview = invalidCompetenceLabels.slice(0, 3).join(', ')
    const suffix = invalidCompetenceLabels.length > 3 ? ' and more.' : '.'
    return {
      payload: null,
      validationMessage:
        `Threshold values must be numbers from 0 to ${FLIGHT_TYPE_THRESHOLD_MAX_VALUE} ` +
        `with up to ${FLIGHT_TYPE_THRESHOLD_MAX_DECIMAL_DIGITS} decimal places. Check ${preview}${suffix}`,
    }
  }

  return {
    payload: { thresholds },
    validationMessage: null,
  }
}

export const sortFlightTypesByName = (flightTypes: CommanderFlightType[]) =>
  [...flightTypes].sort(
    (left, right) =>
      Number(right.isMain) - Number(left.isMain) ||
      left.name.localeCompare(right.name, undefined, { sensitivity: 'base' }) ||
      left.id - right.id,
  )
