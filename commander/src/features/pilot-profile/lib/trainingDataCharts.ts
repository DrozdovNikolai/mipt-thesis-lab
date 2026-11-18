import type { ChartData, ChartOptions, TooltipItem } from 'chart.js'

import type {
  CommanderFlightTypeThreshold,
  PilotCompetenceGradeHistory,
  PilotPositionAverageCompetenceGrade,
  PilotLatestCompletedTrainingCompetenceGrade,
} from '@/entities/commander/types'

export const RADAR_BORDER_COLOR = '#7294D8'
const RADAR_FILL_COLOR = '#D6D5D4'
export const THRESHOLD_RADAR_COLOR = '#B7312E'
export const POSITION_AVERAGE_RADAR_COLOR = '#FFCE00'
export const THRESHOLD_HISTORY_LINE_COLOR = '#D83F2F'
export const HISTORY_LINE_COLOR = '#7294D8'
const FALLBACK_FOREGROUND_COLOR = '#000000'
const RADAR_MAX_FALLBACK = 5

type CompetenceHistoryChartPoint = {
  completedAtMs: number
  dateLabel: string
  fullDateLabel: string
  sessionTitle: string
  score: number
  gradeCode: string
  gradeLabel: string | null
}

const resolveThemeColor = (variableName: string, fallbackColor: string) => {
  if (typeof document === 'undefined') return fallbackColor

  const value = getComputedStyle(document.documentElement).getPropertyValue(variableName).trim()
  return value || fallbackColor
}

const resolveNumericValue = (value: string | number | null | undefined) => {
  if (typeof value === 'number' && Number.isFinite(value)) return value
  if (typeof value === 'string') {
    const parsed = Number(value)
    if (Number.isFinite(parsed)) return parsed
  }
  return null
}

const formatShortDate = (value: string) =>
  new Intl.DateTimeFormat(undefined, {
    month: 'short',
    day: 'numeric',
    year: '2-digit',
  }).format(new Date(value))

const formatFullDate = (value: string) =>
  new Intl.DateTimeFormat(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(value))

const sortLatestGrades = (grades: PilotLatestCompletedTrainingCompetenceGrade[]) =>
  [...grades].sort(
    (left, right) => left.orderIndex - right.orderIndex || left.competenceId - right.competenceId,
  )

const buildThresholdScoreMap = (thresholds: CommanderFlightTypeThreshold[]) =>
  new Map(
    thresholds.flatMap((threshold) => {
      const numericValue = resolveNumericValue(threshold.value)
      return numericValue === null ? [] : [[threshold.competenceId, numericValue] as const]
    }),
  )

const buildPositionAverageScoreMap = (grades: PilotPositionAverageCompetenceGrade[]) =>
  new Map(
    grades.flatMap((grade) => {
      const numericValue = resolveNumericValue(grade.averageScoreNumeric)
      return numericValue === null ? [] : [[grade.competenceId, numericValue] as const]
    }),
  )

const buildCompetenceHistoryChartPoints = (
  history: PilotCompetenceGradeHistory['history'],
): CompetenceHistoryChartPoint[] =>
  [...history]
    .map((entry) => {
      const score = resolveNumericValue(entry.gradeScoreNumeric)
      if (score === null) return null
      return {
        completedAtMs: new Date(entry.completedAt).getTime(),
        dateLabel: formatShortDate(entry.completedAt),
        fullDateLabel: formatFullDate(entry.completedAt),
        sessionTitle: entry.trainingSessionTitle,
        score,
        gradeCode: entry.gradeCode,
        gradeLabel: entry.gradeLabel,
      }
    })
    .filter((entry): entry is CompetenceHistoryChartPoint => entry !== null)
    .sort((left, right) => left.completedAtMs - right.completedAtMs)

export const getLatestCompetenceGradeCode = (
  competenceId: number,
  latestGrades: PilotLatestCompletedTrainingCompetenceGrade[],
  history: PilotCompetenceGradeHistory['history'],
) =>
  latestGrades.find((grade) => grade.competenceId === competenceId)?.gradeCode ??
  history[0]?.gradeCode ??
  '—'

export const createPilotRadarChartData = (
  grades: PilotLatestCompletedTrainingCompetenceGrade[],
  thresholds: CommanderFlightTypeThreshold[] = [],
  positionAverageGrades: PilotPositionAverageCompetenceGrade[] = [],
): ChartData<'radar', (number | null)[], string> => {
  const sortedGrades = sortLatestGrades(grades)
  const thresholdScoreMap = buildThresholdScoreMap(thresholds)
  const positionAverageScoreMap = buildPositionAverageScoreMap(positionAverageGrades)
  const thresholdDataset = sortedGrades.map(
    (grade) => thresholdScoreMap.get(grade.competenceId) ?? null,
  )
  const positionAverageDataset = sortedGrades.map(
    (grade) => positionAverageScoreMap.get(grade.competenceId) ?? null,
  )
  const hasThresholdValues = thresholdDataset.some((value) => value !== null)
  const hasPositionAverageValues = positionAverageDataset.some((value) => value !== null)

  return {
    labels: sortedGrades.map((grade) => grade.competenceCode),
    datasets: [
      ...(hasThresholdValues
        ? [
            {
              label: 'Main threshold',
              data: thresholdDataset,
              borderColor: THRESHOLD_RADAR_COLOR,
              backgroundColor: `${THRESHOLD_RADAR_COLOR}2E`,
              pointBackgroundColor: THRESHOLD_RADAR_COLOR,
              pointBorderColor: THRESHOLD_RADAR_COLOR,
              pointHoverBackgroundColor: THRESHOLD_RADAR_COLOR,
              pointHoverBorderColor: '#FFFFFF',
              borderWidth: 2,
              pointRadius: 2,
              pointHoverRadius: 3,
              fill: true,
              spanGaps: true,
            },
          ]
        : []),
      ...(hasPositionAverageValues
        ? [
            {
              label: 'Position average',
              data: positionAverageDataset,
              borderColor: POSITION_AVERAGE_RADAR_COLOR,
              backgroundColor: `${POSITION_AVERAGE_RADAR_COLOR}33`,
              pointBackgroundColor: POSITION_AVERAGE_RADAR_COLOR,
              pointBorderColor: POSITION_AVERAGE_RADAR_COLOR,
              pointHoverBackgroundColor: POSITION_AVERAGE_RADAR_COLOR,
              pointHoverBorderColor: '#FFFFFF',
              borderWidth: 2,
              pointRadius: 2,
              pointHoverRadius: 3,
              fill: true,
              spanGaps: true,
            },
          ]
        : []),
      {
        label: 'Latest training',
        data: sortedGrades.map((grade) => resolveNumericValue(grade.gradeScoreNumeric)),
        borderColor: RADAR_BORDER_COLOR,
        backgroundColor: `${RADAR_FILL_COLOR}CC`,
        pointBackgroundColor: RADAR_BORDER_COLOR,
        pointBorderColor: RADAR_BORDER_COLOR,
        pointHoverBackgroundColor: RADAR_BORDER_COLOR,
        pointHoverBorderColor: '#FFFFFF',
        borderWidth: 2,
        pointRadius: 4,
        pointHoverRadius: 5,
        fill: true,
      },
    ],
  }
}

export const createPilotRadarChartOptions = (
  grades: PilotLatestCompletedTrainingCompetenceGrade[],
  thresholds: CommanderFlightTypeThreshold[] = [],
  positionAverageGrades: PilotPositionAverageCompetenceGrade[] = [],
): ChartOptions<'radar'> => {
  const labelColor = resolveThemeColor('--color-foreground', FALLBACK_FOREGROUND_COLOR)
  const numericValues = [
    ...grades.map((grade) => resolveNumericValue(grade.gradeScoreNumeric)),
    ...thresholds.map((threshold) => resolveNumericValue(threshold.value)),
    ...positionAverageGrades.map((grade) => resolveNumericValue(grade.averageScoreNumeric)),
  ].filter((value): value is number => value !== null)
  const radarMax =
    numericValues.length > 0
      ? Math.max(RADAR_MAX_FALLBACK, Math.ceil(Math.max(...numericValues)))
      : RADAR_MAX_FALLBACK
  const sortedGrades = sortLatestGrades(grades)

  return {
    responsive: true,
    maintainAspectRatio: false,
    animation: {
      duration: 220,
    },
    elements: {
      line: {
        tension: 0.16,
      },
    },
    plugins: {
      legend: {
        display: false,
      },
      tooltip: {
        backgroundColor: '#0f172a',
        bodyColor: '#f8fafc',
        titleColor: '#f8fafc',
        footerColor: '#cbd5e1',
        padding: 14,
        cornerRadius: 14,
        callbacks: {
          title: (items: TooltipItem<'radar'>[]) => {
            const dataIndex = items[0]?.dataIndex ?? 0
            return sortedGrades[dataIndex]?.competenceName ?? items[0]?.label ?? 'Competence'
          },
          label: (item: TooltipItem<'radar'>) => {
            const score = item.parsed.r
            if (item.dataset.label === 'Main threshold') {
              return `Main threshold: ${score}`
            }
            if (item.dataset.label === 'Position average') {
              return `Position average: ${score}`
            }
            const grade = sortedGrades[item.dataIndex]
            return `${grade?.gradeCode ?? 'Grade'}: ${score}`
          },
          footer: (items: TooltipItem<'radar'>[]) => {
            const dataIndex = items[0]?.dataIndex ?? 0
            if (items[0]?.dataset.label === 'Main threshold') return ''
            if (items[0]?.dataset.label === 'Position average') return ''
            const grade = sortedGrades[dataIndex]
            return grade?.gradeLabel ?? ''
          },
        },
      },
    },
    scales: {
      r: {
        startAngle: 0,
        beginAtZero: true,
        suggestedMin: 0,
        suggestedMax: radarMax,
        angleLines: {
          color: '#B8B8B8',
        },
        grid: {
          color: '#B8B8B8',
        },
        pointLabels: {
          color: labelColor,
          font: {
            size: 11,
            weight: 600,
          },
        },
        ticks: {
          display: false,
          stepSize: 1,
          backdropColor: 'transparent',
        },
      },
    },
  }
}

export const createCompetenceHistoryChartData = (
  history: PilotCompetenceGradeHistory['history'],
  thresholdValue: number | null = null,
): ChartData<'line', number[], string> => {
  const points = buildCompetenceHistoryChartPoints(history)
  const hasThresholdValue = thresholdValue !== null

  return {
    labels: points.map((point) => point.dateLabel),
    datasets: [
      ...(hasThresholdValue
        ? [
            {
              label: 'Main threshold',
              data: points.map(() => thresholdValue),
              borderColor: THRESHOLD_HISTORY_LINE_COLOR,
              backgroundColor: THRESHOLD_HISTORY_LINE_COLOR,
              pointBackgroundColor: THRESHOLD_HISTORY_LINE_COLOR,
              pointBorderColor: THRESHOLD_HISTORY_LINE_COLOR,
              pointHoverBackgroundColor: THRESHOLD_HISTORY_LINE_COLOR,
              pointHoverBorderColor: THRESHOLD_HISTORY_LINE_COLOR,
              pointRadius: 0,
              pointHoverRadius: 0,
              borderWidth: 2,
              tension: 0,
              fill: false,
            },
          ]
        : []),
      {
        label: 'Score',
        data: points.map((point) => point.score),
        borderColor: HISTORY_LINE_COLOR,
        backgroundColor: HISTORY_LINE_COLOR,
        pointBackgroundColor: HISTORY_LINE_COLOR,
        pointBorderColor: '#FFFFFF',
        pointHoverBackgroundColor: HISTORY_LINE_COLOR,
        pointHoverBorderColor: '#FFFFFF',
        pointRadius: 4,
        pointHoverRadius: 5,
        pointBorderWidth: 2,
        borderWidth: 2,
        tension: 0.24,
        fill: false,
      },
    ],
  }
}

export const createCompetenceHistoryChartOptions = (
  history: PilotCompetenceGradeHistory['history'],
  thresholdValue: number | null = null,
): ChartOptions<'line'> => {
  const labelColor = resolveThemeColor('--color-foreground', FALLBACK_FOREGROUND_COLOR)
  const points = buildCompetenceHistoryChartPoints(history)
  const scores = [
    ...points.map((point) => point.score),
    ...(thresholdValue !== null ? [thresholdValue] : []),
  ]
  const minScore = scores.length > 0 ? Math.max(0, Math.floor(Math.min(...scores)) - 1) : 0
  const maxScore = scores.length > 0 ? Math.ceil(Math.max(...scores)) + 1 : RADAR_MAX_FALLBACK

  return {
    responsive: true,
    maintainAspectRatio: false,
    animation: {
      duration: 220,
    },
    plugins: {
      legend: {
        display: false,
      },
      tooltip: {
        backgroundColor: '#0f172a',
        bodyColor: '#f8fafc',
        titleColor: '#f8fafc',
        footerColor: '#cbd5e1',
        padding: 14,
        cornerRadius: 14,
        callbacks: {
          title: (items: TooltipItem<'line'>[]) => {
            if (items[0]?.dataset.label === 'Main threshold') {
              return 'Main threshold'
            }
            const point = points[items[0]?.dataIndex ?? 0]
            return point?.sessionTitle ?? items[0]?.label ?? 'Training session'
          },
          label: (item: TooltipItem<'line'>) => {
            if (item.dataset.label === 'Main threshold') {
              return `Main threshold: ${item.parsed.y}`
            }
            const point = points[item.dataIndex]
            return `${point?.gradeCode ?? 'Score'}: ${item.parsed.y}`
          },
          footer: (items: TooltipItem<'line'>[]) => {
            if (items[0]?.dataset.label === 'Main threshold')
              return 'Single-pilot analytics threshold'
            const point = points[items[0]?.dataIndex ?? 0]
            if (!point) return ''
            return `${point.fullDateLabel}${point.gradeLabel ? ` • ${point.gradeLabel}` : ''}`
          },
        },
      },
    },
    scales: {
      x: {
        border: {
          display: false,
        },
        grid: {
          display: false,
        },
        ticks: {
          color: labelColor,
          font: {
            size: 11,
          },
          maxRotation: 0,
        },
      },
      y: {
        border: {
          display: false,
        },
        grid: {
          color: 'rgba(148, 163, 184, 0.2)',
          lineWidth: 0.75,
        },
        ticks: {
          color: labelColor,
          font: {
            size: 11,
          },
        },
        suggestedMin: minScore,
        suggestedMax: maxScore,
      },
    },
  }
}

export const getCompetenceHistoryChartMinWidth = (historyLength: number) =>
  historyLength > 6 ? Math.max(560, historyLength * 88) : undefined
