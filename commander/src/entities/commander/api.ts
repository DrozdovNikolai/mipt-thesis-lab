import { api } from '@/shared/api/api'
import { endpoints } from '@/shared/api/endpoints'
import type { AircraftAirline, Competence } from '@/entities/training/types'
import type {
  CommanderFlightType,
  CommanderFlightTypeCreatePayload,
  CommanderFlightTypeThresholdsReplacePayload,
  CommanderFlightTypeUpdatePayload,
  CommanderAnalyticsQuery,
  CompetencyAverageTrendResponse,
  CommanderPilotProfile,
  CommanderScenarioLookupPage,
  CompetencyGradeDistributionResponse,
  InstructorGradeDistributionResponse,
  PilotCompatibilityQuery,
  PilotCompatibilityResponse,
  TrainingSessionDetail,
  PilotGradeDistributionResponse,
  PilotTrainingSummary,
  PilotsListPage,
  PilotsListQuery,
  TrainingSessionListPage,
  TrainingSessionsListQuery,
} from './types'

const buildAnalyticsQuery = (query: CommanderAnalyticsQuery = {}) => ({
  aircraftId: query.aircraftId,
  pilotId: query.pilotId,
  ageFromYears: query.ageFromYears,
  ageToYears: query.ageToYears,
  positionId: query.positionId,
  asOfDate: query.asOfDate,
})

export const commanderApi = {
  listAircraft: (signal?: AbortSignal) =>
    api.get<AircraftAirline[]>(endpoints.commander.aircraft, { signal }),
  listPilots: (query: PilotsListQuery = {}, signal?: AbortSignal) =>
    api.get<PilotsListPage>(endpoints.commander.pilots, {
      signal,
      query: {
        q: query.q,
        isActive: query.isActive,
        roleId: query.roleId,
        aircraftId: query.aircraftId,
        sort: query.sort,
        limit: query.limit,
        offset: query.offset,
      },
    }),
  getPilotProfile: (pilotId: string, signal?: AbortSignal) =>
    api.get<CommanderPilotProfile>(`${endpoints.commander.pilots}/${encodeURIComponent(pilotId)}`, {
      signal,
    }),
  getPilotTrainingSummary: (pilotId: string, signal?: AbortSignal) =>
    api.get<PilotTrainingSummary>(
      `${endpoints.commander.pilots}/${encodeURIComponent(pilotId)}/training-summary`,
      { signal },
    ),
  getTrainingSessionDetail: (trainingSessionId: number, signal?: AbortSignal) =>
    api.get<TrainingSessionDetail>(`${endpoints.commander.trainingSessions}/${trainingSessionId}`, {
      signal,
    }),
  downloadTrainingSessionAssessmentReport: (trainingSessionId: number, assessmentId: number) =>
    api.getBlob(
      `${endpoints.commander.trainingSessions}/${trainingSessionId}/assessments/${assessmentId}/report.pdf`,
    ),
  listScenarios: (
    query: { q?: string; aircraftId?: number; limit?: number; offset?: number } = {},
    signal?: AbortSignal,
  ) =>
    api.get<CommanderScenarioLookupPage>(endpoints.commander.scenarios, {
      signal,
      query: {
        q: query.q,
        aircraftId: query.aircraftId,
        limit: query.limit,
        offset: query.offset,
      },
    }),
  listTrainingSessions: (query: TrainingSessionsListQuery = {}, signal?: AbortSignal) =>
    api.get<TrainingSessionListPage>(endpoints.commander.trainingSessions, {
      signal,
      query: {
        completedFrom: query.completedFrom,
        completedTo: query.completedTo,
        scenarioId: query.scenarioId,
        instructorId: query.instructorId,
        participantId: query.participantId,
        cm1Id: query.cm1Id,
        cm2Id: query.cm2Id,
        aircraftId: query.aircraftId,
        limit: query.limit,
        offset: query.offset,
      },
    }),
  listCompetences: () => api.get<Competence[]>(endpoints.commander.competences),
  listFlightTypes: () => api.get<CommanderFlightType[]>(endpoints.commander.flightTypes),
  createFlightType: (payload: CommanderFlightTypeCreatePayload) =>
    api.post<CommanderFlightType>(endpoints.commander.flightTypes, payload),
  updateFlightType: (flightTypeId: number, payload: CommanderFlightTypeUpdatePayload) =>
    api.put<CommanderFlightType>(`${endpoints.commander.flightTypes}/${flightTypeId}`, payload),
  replaceFlightTypeThresholds: (
    flightTypeId: number,
    payload: CommanderFlightTypeThresholdsReplacePayload,
  ) =>
    api.put<CommanderFlightType>(
      `${endpoints.commander.flightTypes}/${flightTypeId}/thresholds`,
      payload,
    ),
  deleteFlightType: (flightTypeId: number) =>
    api.delete<void>(`${endpoints.commander.flightTypes}/${flightTypeId}`),
  getPilotCompatibility: (query: PilotCompatibilityQuery, signal?: AbortSignal) =>
    api.get<PilotCompatibilityResponse>(endpoints.commander.pilotCompatibility, {
      signal,
      query: {
        firstPilotId: query.firstPilotId,
        secondPilotId: query.secondPilotId,
        flightTypeId: query.flightTypeId,
        asOfDate: query.asOfDate,
      },
    }),
  analytics: {
    getCompetencyGradeDistribution: (query: CommanderAnalyticsQuery = {}, signal?: AbortSignal) =>
      api.get<CompetencyGradeDistributionResponse>(
        endpoints.commander.analytics.competenciesGradeDistribution,
        {
          signal,
          query: buildAnalyticsQuery(query),
        },
      ),
    getCompetencyAverageTrend: (query: CommanderAnalyticsQuery = {}, signal?: AbortSignal) =>
      api.get<CompetencyAverageTrendResponse>(
        endpoints.commander.analytics.competenciesAverageTrend,
        {
          signal,
          query: buildAnalyticsQuery(query),
        },
      ),
    getPilotGradeDistribution: (query: CommanderAnalyticsQuery = {}, signal?: AbortSignal) =>
      api.get<PilotGradeDistributionResponse>(
        endpoints.commander.analytics.pilotsGradeDistribution,
        {
          signal,
          query: buildAnalyticsQuery(query),
        },
      ),
    getInstructorGradeDistribution: (query: CommanderAnalyticsQuery = {}, signal?: AbortSignal) =>
      api.get<InstructorGradeDistributionResponse>(
        endpoints.commander.analytics.instructorsGradeDistribution,
        {
          signal,
          query: buildAnalyticsQuery(query),
        },
      ),
  },
}
