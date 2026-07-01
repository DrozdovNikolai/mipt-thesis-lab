import type {
  TrainingSessionDetailAssessment,
  TrainingSessionDetailAssessmentExerciseReport,
  TrainingSessionDetailAssessmentRemark,
  TrainingSessionDetailExercise,
  TrainingSessionDetailExerciseRun,
  TrainingSessionDetailModule,
  TrainingSessionDetailParticipant,
  TrainingSessionDuty,
} from '@/entities/commander/types'
import { getPersonLabel } from '@/features/training-sessions/lib/trainingSessionPresentation'

export const sectionCardClassName = 'rounded-[28px] border border-line bg-surface p-5 shadow-sm'
export const innerCardClassName = 'rounded-2xl border border-line bg-surface-muted px-4 py-4'
export const serviceExerciseLabelByKind = {
  preparation: 'Preparation',
  coffee_break: 'Coffee break',
} as const

export const dutyPresentation: Record<
  TrainingSessionDuty,
  { label: string; color: string; background: string }
> = {
  PF: { label: 'PF', color: '#284692', background: '#DDE5FA' },
  PM: { label: 'PM', color: '#1D7A31', background: '#DDF3E2' },
  NONE: { label: 'No PF/PM duty', color: '#5C6470', background: '#E8EBEF' },
}

export const getExerciseReportLookup = (assessment: TrainingSessionDetailAssessment | null) =>
  new Map<number, TrainingSessionDetailAssessmentExerciseReport>(
    (assessment?.exerciseReports ?? []).map((report) => [report.exerciseId, report]),
  )

export const formatRemarkHashtag = (value: string | null) => {
  const normalized = value?.trim()
  if (!normalized) return null
  return normalized.startsWith('#') ? normalized : `#${normalized}`
}

export const getRemarkMetadataColor = (isPositive: boolean) => (isPositive ? '#01458E' : '#EA2B1F')

export const getExercisePilotRoleMeta = (
  crewMemberNumber: number | null,
  selectedAssessment: TrainingSessionDetailAssessment | null,
) => {
  if (!crewMemberNumber || !selectedAssessment) return null
  const selectedCrewMemberNumber =
    selectedAssessment.trainingRole === 'cm1'
      ? 1
      : selectedAssessment.trainingRole === 'cm2'
        ? 2
        : null
  if (!selectedCrewMemberNumber) return null
  if (crewMemberNumber === selectedCrewMemberNumber) {
    return { label: 'Legacy planned role: Pilot flying', color: '#284692' }
  }
  return { label: 'Legacy planned role: Pilot monitoring', color: '#1D7A31' }
}

export const flattenExercises = (
  modules: TrainingSessionDetailModule[],
): TrainingSessionDetailExercise[] =>
  [...modules]
    .sort((left, right) => left.orderIndex - right.orderIndex || left.id - right.id)
    .flatMap((module) =>
      [...module.exercises]
        .sort((left, right) => left.orderIndex - right.orderIndex || left.id - right.id)
        .map((exercise) => exercise),
    )

export const getExerciseDisplayLabel = (exercise: TrainingSessionDetailExercise) => {
  const normalized = (exercise.displayLabel ?? '').trim()
  if (normalized) return normalized
  if (exercise.kind === 'preparation' || exercise.kind === 'coffee_break') {
    return serviceExerciseLabelByKind[exercise.kind]
  }
  if (exercise.exerciseNumber != null) {
    return `Exercise ${exercise.exerciseNumber}`
  }
  return 'Exercise'
}

export const getExerciseEmptyStateText = (exercise: TrainingSessionDetailExercise) => {
  if (exercise.kind === 'preparation' || exercise.kind === 'coffee_break') {
    return 'This step has no scenario elements.'
  }
  return 'No scenario elements were attached to this exercise.'
}

export const getRemarkOffsetMs = (remark: TrainingSessionDetailAssessmentRemark) =>
  Math.max(0, remark.exerciseOffsetMs ?? remark.exerciseOffsetSec * 1000)

export const getRunRemarks = (
  remarks: TrainingSessionDetailAssessmentRemark[],
  selectedRun: TrainingSessionDetailExerciseRun | null,
) =>
  remarks
    .filter((remark) => {
      if (!selectedRun) return true
      if ((remark.roleProjectionSource ?? remark.timelineSource) === 'LEGACY_STATIC') return true
      return remark.exerciseSessionKey === selectedRun.exerciseSessionKey
    })
    .sort((left, right) => getRemarkOffsetMs(left) - getRemarkOffsetMs(right) || left.id - right.id)

export const getParticipantName = (
  assessmentId: number | null | undefined,
  participants: TrainingSessionDetailParticipant[],
) => {
  if (assessmentId == null) return null
  const participant = participants.find((item) => item.assessmentId === assessmentId)
  if (!participant) return `Assessment ${assessmentId}`
  return getPersonLabel(participant.firstName, participant.lastName, `Assessment ${assessmentId}`)
}
