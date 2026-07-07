import type {
  TrainingSessionDetailLatestCrewSwap,
  TrainingSessionDetailModule,
  TrainingSessionDetailParticipant,
} from '@/entities/commander/types'
import { formatTrainingDurationMs } from '@/features/training-session-detail/lib/crewTimelinePresentation'
import { getPersonLabel } from '@/features/training-sessions/lib/trainingSessionPresentation'

export const getParticipantName = (participant: TrainingSessionDetailParticipant) =>
  getPersonLabel(
    participant.firstName,
    participant.lastName,
    `Assessment ${participant.assessmentId}`,
  )

export const getAssessmentName = (
  participants: TrainingSessionDetailParticipant[],
  assessmentId: number,
) => {
  const participant = participants.find((item) => item.assessmentId === assessmentId)
  return participant ? getParticipantName(participant) : `Assessment ${assessmentId}`
}

export const getMappingLabel = (
  participants: TrainingSessionDetailParticipant[],
  cm1AssessmentId: number,
  cm2AssessmentId: number,
) =>
  `CM1: ${getAssessmentName(participants, cm1AssessmentId)} · CM2: ${getAssessmentName(participants, cm2AssessmentId)}`

export const formatAcceptedAt = (value: string) => {
  const acceptedAt = new Date(value)
  if (Number.isNaN(acceptedAt.getTime())) return value
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: 'medium',
    timeStyle: 'medium',
  }).format(acceptedAt)
}

export const getLatestSwapContext = (
  latestSwap: TrainingSessionDetailLatestCrewSwap,
  modules: TrainingSessionDetailModule[],
) => {
  if (latestSwap.eventScope === 'SESSION') return 'Between exercises'

  const exercise = modules
    .flatMap((module) => module.exercises)
    .find((item) => item.id === latestSwap.trainingSessionExerciseId)
  const run = exercise?.runs?.find(
    (item) => item.exerciseSessionKey === latestSwap.exerciseSessionKey,
  )
  const exerciseLabel =
    exercise?.displayLabel?.trim() ||
    (exercise?.exerciseNumber != null ? `Exercise ${exercise.exerciseNumber}` : 'Exercise')
  const attemptLabel = run ? `Attempt ${run.runIndex}` : 'Exercise attempt'
  const offsetLabel =
    latestSwap.exerciseOffsetMs == null
      ? null
      : formatTrainingDurationMs(latestSwap.exerciseOffsetMs)
  return [exerciseLabel, attemptLabel, offsetLabel].filter(Boolean).join(' · ')
}
