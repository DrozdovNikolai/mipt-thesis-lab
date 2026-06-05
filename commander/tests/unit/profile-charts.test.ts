import { describe, expect, it } from 'vitest'
import {
  createPilotRadarChartData,
  createCompetenceHistoryChartData,
} from '@/features/pilot-profile/lib/trainingDataCharts'
import type {
  CommanderFlightTypeThreshold,
  PilotLatestCompletedTrainingCompetenceGrade,
  PilotPositionAverageCompetenceGrade,
} from '@/entities/commander/types'

const grade = (
  id: number,
  orderIndex: number,
  score: number | null,
): PilotLatestCompletedTrainingCompetenceGrade => ({
  competenceId: id,
  competenceCode: `C${id}`,
  competenceName: `Competence ${id}`,
  orderIndex,
  gradeCode: score === null ? 'NA' : String(score),
  gradeScoreNumeric: score,
  gradeLabel: null,
  gradeColorHex: null,
})
describe('profile chart values', () => {
  it('sorts all datasets on the same axes while keeping missing grades distinct from zero', () => {
    const grades = [grade(2, 20, null), grade(1, 10, 0), grade(3, 30, 4)]
    const thresholds = [
      { competenceId: 1, value: '0' },
      { competenceId: 3, value: '3' },
    ] as CommanderFlightTypeThreshold[]
    const averages = [
      { competenceId: 2, averageScoreNumeric: '2.5' },
    ] as PilotPositionAverageCompetenceGrade[]
    const chart = createPilotRadarChartData(grades, thresholds, averages)
    expect(chart.labels).toEqual(['C1', 'C2', 'C3'])
    expect(chart.datasets.map((dataset) => [dataset.label, dataset.data])).toEqual([
      ['Main threshold', [0, null, 3]],
      ['Position average', [null, 2.5, null]],
      ['Latest training', [0, null, 4]],
    ])
    expect(grades.map((item) => item.competenceId)).toEqual([2, 1, 3])
  })
  it('does not invent a threshold or average when none exists', () => {
    const chart = createPilotRadarChartData([])
    expect(chart.labels).toEqual([])
    expect(chart.datasets.map((dataset) => dataset.label)).toEqual(['Latest training'])
    expect(chart.datasets[0]!.data).toEqual([])
  })
  it('orders history chronologically, omits missing scores, and retains a zero threshold', () => {
    const chart = createCompetenceHistoryChartData(
      [
        {
          trainingSessionId: 2,
          trainingSessionTitle: 'Later',
          completedAt: '2026-02-01T12:00:00Z',
          gradeCode: '4',
          gradeLabel: null,
          gradeScoreNumeric: '4',
          gradeColorHex: null,
        },
        {
          trainingSessionId: 3,
          trainingSessionTitle: 'Missing',
          completedAt: '2026-03-01T12:00:00Z',
          gradeCode: 'NA',
          gradeLabel: null,
          gradeScoreNumeric: null,
          gradeColorHex: null,
        },
        {
          trainingSessionId: 1,
          trainingSessionTitle: 'Earlier',
          completedAt: '2026-01-01T12:00:00Z',
          gradeCode: '0',
          gradeLabel: null,
          gradeScoreNumeric: 0,
          gradeColorHex: null,
        },
      ],
      0,
    )
    expect(chart.datasets.map((dataset) => [dataset.label, dataset.data])).toEqual([
      ['Main threshold', [0, 0]],
      ['Score', [0, 4]],
    ])
  })
})
