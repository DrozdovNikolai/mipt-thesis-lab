import type { SessionUser } from '@/entities/session/types'

export const pilotSortOptions = [
  'createdAtDesc',
  'createdAtAsc',
  'loginAsc',
  'loginDesc',
  'emailAsc',
  'emailDesc',
  'lastNameAsc',
  'lastNameDesc',
] as const

export type PilotSortOption = (typeof pilotSortOptions)[number]

export type PilotsListQuery = {
  q?: string
  isActive?: boolean
  roleId?: string
  aircraftId?: number
  sort?: PilotSortOption
  limit?: number
  offset?: number
}

export type PilotsListPage = {
  total: number
  limit: number
  offset: number
  items: SessionUser[]
}

export type CommanderPilotProfile = {
  id: string
  fullName: string | null
  firstName: string | null
  lastName: string | null
  photoUrl?: string | null
  positionId: number | null
  position: string | null
  aircraftIds: number[]
  aircraftCodes: string[]
  rating: string | null
  phone: string | null
  email: string
}

export type CommanderScenarioLookupItem = {
  id: number
  title: string
  status: string
  aircraftId: number | null
  aircraftCode: string | null
}

export type CommanderScenarioLookupPage = {
  total: number
  limit: number
  offset: number
  items: CommanderScenarioLookupItem[]
}

export type TrainingSessionsListQuery = {
  completedFrom?: string
  completedTo?: string
  scenarioId?: number
  instructorId?: string
  participantId?: string
  /** @deprecated Initial CM1 assignment only. Use participantId for new UI. */
  cm1Id?: string
  /** @deprecated Initial CM2 assignment only. Use participantId for new UI. */
  cm2Id?: string
  aircraftId?: number
  limit?: number
  offset?: number
}

export type TrainingSessionPreviousDay = {
  id: number
  title: string
  dayIndex?: number | null
}

export type TrainingSessionListItem = {
  id: number
  title: string
  dayTitle?: string | null
  dayIndex?: number | null
  completedAt: string | null
  instructorId: string | null
  instructorFirstName: string | null
  instructorLastName: string | null
  instructorPhotoUrl?: string | null
  cm1Id: string | null
  cm1FirstName: string | null
  cm1LastName: string | null
  cm1PhotoUrl?: string | null
  cm2Id: string | null
  cm2FirstName: string | null
  cm2LastName: string | null
  cm2PhotoUrl?: string | null
  aircraftId: number | null
  previousDays: TrainingSessionPreviousDay[]
}

export type TrainingSessionListPage = {
  total: number
  limit: number
  offset: number
  items: TrainingSessionListItem[]
}

export type PilotLatestCompletedTrainingCompetenceGrade = {
  competenceId: number
  competenceCode: string
  competenceName: string
  orderIndex: number
  gradeCode: string
  gradeLabel: string | null
  gradeScoreNumeric: string | number | null
  gradeColorHex: string | null
}

export type PilotLatestCompletedTraining = {
  trainingSessionId: number
  title: string
  completedAt: string
  trainingRole: string | null
  initialCrewSlot?: TrainingSessionCrewSlot | null
  finalCrewSlot?: TrainingSessionCrewSlot | null
  swapCount?: number
  pfDurationMs?: number
  pmDurationMs?: number
  roleProjectionSource?: TrainingSessionProjectionSource
  grades: PilotLatestCompletedTrainingCompetenceGrade[]
}

export type PilotCompetenceGradeHistoryEntry = {
  trainingSessionId: number
  trainingSessionTitle: string
  completedAt: string
  gradeCode: string
  gradeLabel: string | null
  gradeScoreNumeric: string | number | null
  gradeColorHex: string | null
}

export type PilotCompetenceGradeHistory = {
  competenceId: number
  competenceCode: string
  competenceName: string
  orderIndex: number
  history: PilotCompetenceGradeHistoryEntry[]
}

export type PilotCompletedTrainingSession = TrainingSessionListItem & {
  trainingRole: string | null
  initialCrewSlot?: TrainingSessionCrewSlot | null
  finalCrewSlot?: TrainingSessionCrewSlot | null
  swapCount?: number
  pfDurationMs?: number
  pmDurationMs?: number
  roleProjectionSource?: TrainingSessionProjectionSource
}

export type PilotPositionAverageCompetenceGrade = {
  competenceId: number
  competenceCode: string
  competenceName: string
  orderIndex: number
  averageScoreNumeric: string | number
}

export type PilotTrainingSummary = {
  pilot: CommanderPilotProfile
  latestCompletedTraining: PilotLatestCompletedTraining | null
  positionAverageGrades: PilotPositionAverageCompetenceGrade[]
  competenceHistories: PilotCompetenceGradeHistory[]
  completedTrainingSessions: PilotCompletedTrainingSession[]
}

export type TrainingSessionDetailSession = TrainingSessionListItem & {
  scenarioId: number | null
  scenarioDayModuleId: number | null
  dayIndex: number | null
  daysCount: number | null
  aircraftCode: string | null
  notes: string | null
}

export type TrainingSessionDetailExerciseCompetence = {
  id: number
  code: string
  name: string
  orderIndex: number
}

export type TrainingSessionDetailExerciseElement = {
  id: number
  elementId: number
  elementName: string
  orderIndex: number
  details: string | null
}

export type TrainingSessionCrewSlot = 'CM1' | 'CM2'
export type TrainingSessionDuty = 'PF' | 'PM' | 'NONE'
export type TrainingSessionProjectionSource = 'ACTUAL_TIMELINE' | 'LEGACY_PLANNED'

export type TrainingSessionDetailParticipant = {
  assessmentId: number
  pilotId: string | null
  firstName: string | null
  lastName: string | null
  photoUrl: string | null
  initialCrewSlot: TrainingSessionCrewSlot
  finalCrewSlot: TrainingSessionCrewSlot
  pfDurationMs: number
  pmDurationMs: number
}

export type TrainingSessionDetailCrewRuntime = {
  projectionSource: TrainingSessionProjectionSource
  sealed: boolean
  initialEventId: string | null
  currentEventId: string | null
  initialCm1AssessmentId: number
  initialCm2AssessmentId: number
  finalCm1AssessmentId: number
  finalCm2AssessmentId: number
  swapCount: number
  /** Optional only while Commander is rolling ahead of the latest-state backend contract. */
  latestSwap?: TrainingSessionDetailLatestCrewSwap | null
}

export type TrainingSessionDetailLatestCrewSwap = {
  eventId: string
  serverRevision: number
  acceptedAt: string
  eventScope: 'SESSION' | 'EXERCISE_RUN'
  trainingSessionExerciseId: number | null
  exerciseSessionKey: string | null
  exerciseOffsetMs: number | null
  cm1AssessmentIdBefore: number
  cm2AssessmentIdBefore: number
  cm1AssessmentIdAfter: number
  cm2AssessmentIdAfter: number
}

export type TrainingSessionDetailExerciseRun = {
  exerciseSessionKey: string
  runIndex: number
  status: 'COMPLETED' | 'ABANDONED'
  activeDurationMs: number
}

export type TrainingSessionDetailExercise = {
  id: number
  clientUid: string
  moduleId: number
  kind: 'standard' | 'preparation' | 'coffee_break' | 'individual'
  displayLabel: string
  exerciseNumber: number | null
  orderIndex: number
  durationMinutes: number | null
  crewMemberNumber: number | null
  resolvedForAssessmentId: number | null
  /** Optional only while Commander is rolling against a pre-live-swap backend. */
  runs?: TrainingSessionDetailExerciseRun[]
  elements: TrainingSessionDetailExerciseElement[]
  competences: TrainingSessionDetailExerciseCompetence[]
}

export type TrainingSessionDetailModule = {
  id: number
  clientUid: string
  orderIndex: number
  durationMinutes: number | null
  contentSubcolumnId: number | null
  contentSubcolumnName: string | null
  exercises: TrainingSessionDetailExercise[]
}

export type TrainingSessionDetailAssessmentFinalReport = {
  id: number
  competenceId: number
  competenceCode: string
  competenceName: string
  orderIndex: number
  gradeCode: string
  gradeLabel: string | null
  gradeScoreNumeric: string | number | null
  gradeColorHex: string | null
}

export type TrainingSessionDetailAssessmentRemark = {
  id: number
  clientReportId?: string | null
  timelineSource?: 'TIMELINE' | 'LEGACY_STATIC'
  exerciseId: number
  timestamp: string
  exerciseOffsetSec: number
  exerciseOffsetMs?: number | null
  exerciseSessionKey: string
  assignmentEventIdAtObservation?: string | null
  crewSlotAtObservation?: TrainingSessionCrewSlot | null
  dutyAtObservation?: TrainingSessionDuty
  roleProjectionSource?: 'TIMELINE' | 'LEGACY_STATIC'
  competenceId: number | null
  competenceCode: string | null
  competenceName: string | null
  behaviouralIndicatorId: number | null
  behaviouralIndicatorCode: string | null
  behaviouralIndicatorName: string | null
  isPositive: boolean
  hashtag: string | null
  comment: string | null
}

export type TrainingSessionDetailAssessmentExerciseReport = {
  exerciseId: number
  remarkCount: number
  positiveRemarkCount: number
  negativeRemarkCount: number
  remarks: TrainingSessionDetailAssessmentRemark[]
}

export type TrainingSessionDetailAssessmentAiReview = {
  id: number
  competenceId: number | null
  competenceCode: string | null
  competenceName: string | null
  text: string
}

export type TrainingSessionDetailAssessment = {
  id: number
  trainingRole: string
  pilotId: string | null
  pilotFirstName: string | null
  pilotLastName: string | null
  summary: string | null
  result: boolean | null
  signedAt: string | null
  finalReports: TrainingSessionDetailAssessmentFinalReport[]
  exerciseReports: TrainingSessionDetailAssessmentExerciseReport[]
  aiReviews: TrainingSessionDetailAssessmentAiReview[]
}

export type TrainingSessionDetail = {
  session: TrainingSessionDetailSession
  /** Optional only for rolling compatibility with a pre-live-swap backend. */
  crewRuntime?: TrainingSessionDetailCrewRuntime
  /** Optional only for rolling compatibility with a pre-live-swap backend. */
  participants?: TrainingSessionDetailParticipant[]
  modules: TrainingSessionDetailModule[]
  assessments: TrainingSessionDetailAssessment[]
}

export type CommanderAnalyticsQuery = {
  aircraftId?: number
  pilotId?: string
  ageFromYears?: number
  ageToYears?: number
  positionId?: number
  asOfDate?: string
}

export type PilotCompatibilityQuery = {
  firstPilotId: string
  secondPilotId: string
  flightTypeId: number
  asOfDate?: string
}

export type CommanderAnalyticsFilters = {
  aircraftId: number | null
  pilotId: string | null
  ageFromYears: number | null
  ageToYears: number | null
  positionId: number | null
  asOfDate: string | null
}

export type AnalyticsGradeBucketBase = {
  gradeCode: string
  gradeLabel: string | null
  gradeScoreNumeric: string | number | null
  gradeColorHex: string | null
}

export type CompetencyGradeDistributionBucket = AnalyticsGradeBucketBase & {
  pilotCount: number
}

export type GradeDistributionBucket = AnalyticsGradeBucketBase & {
  gradeCount: number
}

export type CompetencyGradeDistributionItem = {
  competenceId: number
  competenceCode: string
  competenceName: string
  orderIndex: number
  assessedPilotCount: number
  grades: CompetencyGradeDistributionBucket[]
}

export type PilotGradeDistributionItem = {
  pilotId: string
  firstName: string | null
  lastName: string | null
  assessedGradeCount: number
  grades: GradeDistributionBucket[]
}

export type InstructorGradeDistributionItem = {
  instructorId: string
  firstName: string | null
  lastName: string | null
  assessedGradeCount: number
  grades: GradeDistributionBucket[]
}

export type GradeDistributionFilters = {
  aircraftId: number | null
  pilotId: string | null
  ageFromYears: number | null
  ageToYears: number | null
  positionId: number | null
  asOfDate: string | null
}

export type CompetencyGradeDistributionResponse = {
  totalPilots: number
  pilotsWithCompletedTraining: number
  filters: GradeDistributionFilters
  items: CompetencyGradeDistributionItem[]
}

export type CompetencyAverageTrendPoint = {
  periodStart: string
  periodEnd: string
  periodLabel: string
  averageScoreNumeric: string | number
  pilotCount: number
}

export type CompetencyAverageTrendItem = {
  competenceId: number
  competenceCode: string
  competenceName: string
  orderIndex: number
  points: CompetencyAverageTrendPoint[]
}

export type CompetencyAverageTrendResponse = {
  totalPilots: number
  pilotsWithCompletedTraining: number
  filters: GradeDistributionFilters
  items: CompetencyAverageTrendItem[]
}

export type PilotGradeDistributionResponse = {
  totalPilots: number
  pilotsWithCompletedTraining: number
  filters: GradeDistributionFilters
  items: PilotGradeDistributionItem[]
}

export type InstructorGradeDistributionResponse = {
  totalInstructors: number
  instructorsWithCompletedTraining: number
  filters: GradeDistributionFilters
  items: InstructorGradeDistributionItem[]
}

export type CommanderFlightType = {
  id: number
  airlineId: number
  name: string
  isMain: boolean
  createdAt: string
  updatedAt: string
  thresholds: CommanderFlightTypeThreshold[]
}

export type CommanderFlightTypeThreshold = {
  id: number
  competenceId: number
  competenceCode: string
  competenceName: string
  competenceOrderIndex: number
  value: string | number
  createdAt: string
  updatedAt: string
}

export type CommanderFlightTypeCreatePayload = {
  name: string
  isMain?: boolean
}

export type CommanderFlightTypeUpdatePayload = {
  name?: string
  isMain?: boolean
}

export type CommanderFlightTypeThresholdInput = {
  competenceId: number
  value: string | number
}

export type CommanderFlightTypeThresholdsReplacePayload = {
  thresholds: CommanderFlightTypeThresholdInput[]
}

export type PilotCompatibilityPilot = {
  id: string
  firstName: string | null
  lastName: string | null
  hasCompletedTraining: boolean
}

export type PilotCompatibilityFlightType = {
  id: number
  name: string
}

export type PilotCompatibilityItem = {
  competenceId: number
  competenceCode: string
  competenceName: string
  orderIndex: number
  compatible: boolean
  thresholdConfigured: boolean
  requiredSum: string | number | null
  actualSum: string | number | null
  firstPilotValue: string | number | null
  secondPilotValue: string | number | null
}

export type PilotCompatibilityResponse = {
  firstPilot: PilotCompatibilityPilot
  secondPilot: PilotCompatibilityPilot
  flightType: PilotCompatibilityFlightType
  asOfDate: string | null
  items: PilotCompatibilityItem[]
}
