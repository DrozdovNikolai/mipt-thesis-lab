import type { ChartData, ChartOptions, TooltipItem } from 'chart.js'

import type {
  CompetencyAverageTrendItem,
  CompetencyGradeDistributionItem,
  InstructorGradeDistributionItem,
  PilotGradeDistributionItem,
} from '@/entities/commander/types'

type DistributionRowGrade = {
  gradeCode: string
  gradeLabel: string | null
  gradeScoreNumeric: string | number | null
  gradeColorHex: string | null
  value: number
}

type DistributionRow = {
  label: string
  grades: DistributionRowGrade[]
}

type GradeDistributionChartOptionsConfig = {
  indexAxis?: 'x' | 'y'
  rotateCategoryLabels?: boolean
}

export type InstructorScoreSpreadFilter = 'all' | 'low' | 'medium' | 'high'

const FALLBACK_GRADE_COLORS = ['#0f172a', '#2563eb', '#0f766e', '#d97706', '#dc2626', '#7c3aed']
const FALLBACK_FOREGROUND_COLOR = '#000000'
const COMPETENCY_TREND_LINE_COLOR = '#7294D8'

const resolveFallbackColor = (index: number) =>
  FALLBACK_GRADE_COLORS[index % FALLBACK_GRADE_COLORS.length]
const resolveThemeColor = (variableName: string, fallbackColor: string) => {
  if (typeof document === 'undefined') return fallbackColor

  const value = getComputedStyle(document.documentElement).getPropertyValue(variableName).trim()
  return value || fallbackColor
}

const resolveTooltipValue = (value: number | null) => value ?? 0

const resolveTooltipAxisValue = (item: TooltipItem<'bar'>) =>
  resolveTooltipValue(item.chart.options.indexAxis === 'y' ? item.parsed.x : item.parsed.y)

const resolveNumericGradeValue = (value: string | number | null | undefined) => {
  if (typeof value === 'number' && Number.isFinite(value)) return value
  if (typeof value === 'string') {
    const parsed = Number(value)
    if (Number.isFinite(parsed)) return parsed
  }
  return null
}

const resolveColor = (color: string | null, index: number) => {
  const normalized = color?.trim()
  return normalized && normalized.startsWith('#') ? normalized : resolveFallbackColor(index)
}

const resolveGradeDisplayLabel = (label: string | null) => {
  const normalized = label?.trim()
  return normalized || 'Unlabeled grade'
}

const resolvePersonLabel = (
  firstName: string | null | undefined,
  lastName: string | null | undefined,
  fallbackLabel: string,
) => {
  const value = [firstName?.trim(), lastName?.trim()].filter(Boolean).join(' ').trim()
  return value || fallbackLabel
}

const resolveWeightedAverageGradeScore = (
  grades: Array<{
    gradeCount: number
    gradeScoreNumeric: string | number | null
  }>,
) => {
  const weightedTotal = grades.reduce((total, grade) => {
    const numericScore = resolveNumericGradeValue(grade.gradeScoreNumeric)
    if (numericScore === null || grade.gradeCount <= 0) return total
    return total + numericScore * grade.gradeCount
  }, 0)

  const totalCount = grades.reduce((total, grade) => {
    const numericScore = resolveNumericGradeValue(grade.gradeScoreNumeric)
    if (numericScore === null || grade.gradeCount <= 0) return total
    return total + grade.gradeCount
  }, 0)

  if (totalCount === 0) return null
  return weightedTotal / totalCount
}

const resolveWeightedVariance = (
  grades: Array<{
    gradeCount: number
    gradeScoreNumeric: string | number | null
  }>,
) => {
  const averageScore = resolveWeightedAverageGradeScore(grades)
  if (averageScore === null) return null

  let totalCount = 0
  const weightedVariance = grades.reduce((total, grade) => {
    const numericScore = resolveNumericGradeValue(grade.gradeScoreNumeric)
    if (numericScore === null || grade.gradeCount <= 0) return total
    totalCount += grade.gradeCount
    return total + grade.gradeCount * (numericScore - averageScore) ** 2
  }, 0)

  if (totalCount === 0) return null
  return weightedVariance / totalCount
}

const collectActiveNumericScores = (
  grades: Array<{
    gradeCount: number
    gradeScoreNumeric: string | number | null
  }>,
) =>
  grades.reduce<number[]>((scores, grade) => {
    const numericScore = resolveNumericGradeValue(grade.gradeScoreNumeric)
    if (numericScore === null || grade.gradeCount <= 0) return scores
    scores.push(numericScore)
    return scores
  }, [])

const resolveScoreSpreadBucket = ({
  grades,
  globalMinimumScore,
  globalMaximumScore,
}: {
  grades: Array<{
    gradeCount: number
    gradeScoreNumeric: string | number | null
  }>
  globalMinimumScore: number | null
  globalMaximumScore: number | null
}): Exclude<InstructorScoreSpreadFilter, 'all'> | null => {
  if (globalMinimumScore === null || globalMaximumScore === null) return null

  const activeScores = collectActiveNumericScores(grades)
  if (activeScores.length === 0) return null

  const fullScaleRange = globalMaximumScore - globalMinimumScore
  if (fullScaleRange <= 0) return 'high'

  const usedScoreRange = Math.max(...activeScores) - Math.min(...activeScores)
  const normalizedSpread = usedScoreRange / fullScaleRange

  if (normalizedSpread <= 1 / 3) return 'low'
  if (normalizedSpread <= 2 / 3) return 'medium'
  return 'high'
}

const normalizePercentageFilterValue = (value: number | null | undefined) => {
  if (typeof value !== 'number' || !Number.isFinite(value) || value <= 0) return null
  return Math.min(Math.max(value, 0), 100)
}

const resolveExtremeUsagePercentages = ({
  grades,
  globalMinimumScore,
  globalMaximumScore,
}: {
  grades: Array<{
    gradeCount: number
    gradeScoreNumeric: string | number | null
  }>
  globalMinimumScore: number | null
  globalMaximumScore: number | null
}) => {
  let totalCount = 0
  let lowestGradeCount = 0
  let highestGradeCount = 0

  grades.forEach((grade) => {
    const numericScore = resolveNumericGradeValue(grade.gradeScoreNumeric)
    if (numericScore === null || grade.gradeCount <= 0) return
    totalCount += grade.gradeCount
    if (numericScore === globalMinimumScore) lowestGradeCount += grade.gradeCount
    if (numericScore === globalMaximumScore) highestGradeCount += grade.gradeCount
  })

  if (totalCount === 0) {
    return {
      lowestGradeUsagePercent: null,
      highestGradeUsagePercent: null,
      extremeGradeUsagePercent: null,
    }
  }

  return {
    lowestGradeUsagePercent: (lowestGradeCount / totalCount) * 100,
    highestGradeUsagePercent: (highestGradeCount / totalCount) * 100,
    extremeGradeUsagePercent: ((lowestGradeCount + highestGradeCount) / totalCount) * 100,
  }
}

const compareRankedPilots = (
  left: { averageScore: number | null; label: string; pilotId: string },
  right: { averageScore: number | null; label: string; pilotId: string },
  direction: 'asc' | 'desc',
) => {
  if (
    left.averageScore !== null &&
    right.averageScore !== null &&
    left.averageScore !== right.averageScore
  ) {
    return direction === 'asc'
      ? left.averageScore - right.averageScore
      : right.averageScore - left.averageScore
  }
  if (left.averageScore !== null) return -1
  if (right.averageScore !== null) return 1

  const labelComparison = left.label.localeCompare(right.label)
  if (labelComparison !== 0) return labelComparison
  return left.pilotId.localeCompare(right.pilotId)
}

const normalizeRankFilterValue = (value: number | null | undefined) => {
  if (typeof value !== 'number' || !Number.isFinite(value) || value <= 0) return null
  return Math.floor(value)
}

const normalizeNonNegativeFilterValue = (value: number | null | undefined) => {
  if (typeof value !== 'number' || !Number.isFinite(value) || value < 0) return null
  return value
}

const collectGradeDefinitions = (rows: DistributionRow[]) => {
  const definitions = new Map<
    string,
    {
      code: string
      label: string | null
      color: string
      score: number | null
      sequence: number
    }
  >()

  rows.forEach((row) => {
    row.grades.forEach((grade) => {
      if (definitions.has(grade.gradeCode)) return
      definitions.set(grade.gradeCode, {
        code: grade.gradeCode,
        label: grade.gradeLabel,
        color: resolveColor(grade.gradeColorHex, definitions.size),
        score:
          resolveNumericGradeValue(grade.gradeScoreNumeric) ??
          resolveNumericGradeValue(grade.gradeCode),
        sequence: definitions.size,
      })
    })
  })

  return Array.from(definitions.values()).sort((left, right) => {
    if (left.score !== null && right.score !== null) {
      return left.score - right.score
    }
    if (left.score !== null) return -1
    if (right.score !== null) return 1
    return right.sequence - left.sequence
  })
}

export const createGradeDistributionChartOptions = ({
  indexAxis = 'x',
  rotateCategoryLabels = false,
}: GradeDistributionChartOptionsConfig = {}): ChartOptions<'bar'> => {
  const isHorizontal = indexAxis === 'y'
  const labelColor = resolveThemeColor('--color-foreground', FALLBACK_FOREGROUND_COLOR)

  return {
    responsive: true,
    maintainAspectRatio: false,
    indexAxis,
    animation: {
      duration: 220,
    },
    interaction: {
      mode: 'index',
      axis: isHorizontal ? 'y' : 'x',
      intersect: true,
    },
    hover: {
      mode: 'index',
      axis: isHorizontal ? 'y' : 'x',
      intersect: true,
    },
    plugins: {
      legend: {
        position: 'top',
        labels: {
          color: labelColor,
          boxHeight: 10,
          boxWidth: 10,
          padding: 12,
          usePointStyle: true,
          font: {
            size: 11,
            weight: 600,
          },
        },
      },
      tooltip: {
        backgroundColor: '#0f172a',
        bodyColor: '#f8fafc',
        footerColor: '#cbd5e1',
        padding: 16,
        titleColor: '#f8fafc',
        titleFont: {
          size: 16,
          weight: 700,
        },
        bodyFont: {
          size: 18,
          weight: 700,
        },
        footerFont: {
          size: 15,
          weight: 600,
        },
        bodySpacing: 8,
        boxPadding: 4,
        cornerRadius: 14,
        itemSort: (left: TooltipItem<'bar'>, right: TooltipItem<'bar'>) =>
          right.datasetIndex - left.datasetIndex,
        callbacks: {
          label: (context: TooltipItem<'bar'>) =>
            `${context.dataset.label ?? 'Grade'}: ${resolveTooltipAxisValue(context)}`,
          footer: (items: TooltipItem<'bar'>[]) =>
            `Total: ${items.reduce((total, item) => total + resolveTooltipAxisValue(item), 0)}`,
        },
      },
    },
    scales: {
      x: isHorizontal
        ? {
            stacked: true,
            beginAtZero: true,
            border: {
              display: false,
            },
            grid: {
              color: 'rgba(148, 163, 184, 0.18)',
              lineWidth: 0.75,
            },
            ticks: {
              color: labelColor,
              precision: 0,
              font: {
                size: 11,
              },
            },
          }
        : {
            stacked: true,
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
              maxRotation: rotateCategoryLabels ? 50 : 0,
              minRotation: rotateCategoryLabels ? 50 : 0,
            },
          },
      y: isHorizontal
        ? {
            stacked: true,
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
            },
          }
        : {
            stacked: true,
            beginAtZero: true,
            border: {
              display: false,
            },
            grid: {
              color: 'rgba(148, 163, 184, 0.18)',
              lineWidth: 0.75,
            },
            ticks: {
              color: labelColor,
              precision: 0,
              font: {
                size: 11,
              },
            },
          },
    },
  }
}

export const buildGradeDistributionChartData = (
  rows: DistributionRow[],
): ChartData<'bar', number[], string> => {
  const gradeDefinitions = collectGradeDefinitions(rows)

  return {
    labels: rows.map((row) => row.label),
    datasets: gradeDefinitions.map((grade) => ({
      label: resolveGradeDisplayLabel(grade.label),
      data: rows.map((row) => row.grades.find((item) => item.gradeCode === grade.code)?.value ?? 0),
      backgroundColor: grade.color,
      borderColor: grade.color,
      borderRadius: 0,
      borderSkipped: false,
      borderWidth: 0,
    })),
  }
}

export const getGradeDistributionChartMinWidth = (itemCount: number) =>
  itemCount > 10 ? Math.max(840, itemCount * 80) : undefined

export const getHorizontalGradeDistributionChartHeight = (itemCount: number) =>
  Math.max(240, itemCount * 34)

export const mapCompetencyDistributionRows = (
  items: CompetencyGradeDistributionItem[],
): DistributionRow[] =>
  items.map((item) => ({
    label: item.competenceCode,
    grades: item.grades.map((grade) => ({
      gradeCode: grade.gradeCode,
      gradeLabel: grade.gradeLabel,
      gradeScoreNumeric: grade.gradeScoreNumeric,
      gradeColorHex: grade.gradeColorHex,
      value: grade.pilotCount,
    })),
  }))

export const createCompetencyAverageTrendChartData = (
  item: CompetencyAverageTrendItem | null,
): ChartData<'line', number[], string> => {
  const points = item?.points ?? []

  return {
    labels: points.map((point) => point.periodLabel),
    datasets: [
      {
        label: 'Half-year average',
        data: points.map((point) => resolveNumericGradeValue(point.averageScoreNumeric) ?? 0),
        borderColor: COMPETENCY_TREND_LINE_COLOR,
        backgroundColor: COMPETENCY_TREND_LINE_COLOR,
        pointBackgroundColor: COMPETENCY_TREND_LINE_COLOR,
        pointBorderColor: '#FFFFFF',
        pointHoverBackgroundColor: COMPETENCY_TREND_LINE_COLOR,
        pointHoverBorderColor: '#FFFFFF',
        pointRadius: 4,
        pointHoverRadius: 5,
        pointBorderWidth: 2,
        borderWidth: 2,
        tension: 0.22,
        fill: false,
      },
    ],
  }
}

export const createCompetencyAverageTrendChartOptions = (
  item: CompetencyAverageTrendItem | null,
): ChartOptions<'line'> => {
  const labelColor = resolveThemeColor('--color-foreground', FALLBACK_FOREGROUND_COLOR)
  const points = item?.points ?? []
  const scores = points
    .map((point) => resolveNumericGradeValue(point.averageScoreNumeric))
    .filter((score): score is number => score !== null)
  const minScore = scores.length > 0 ? Math.max(0, Math.floor(Math.min(...scores)) - 1) : 0
  const maxScore = scores.length > 0 ? Math.ceil(Math.max(...scores)) + 1 : 5

  return {
    responsive: true,
    maintainAspectRatio: false,
    animation: {
      duration: 220,
    },
    interaction: {
      mode: 'index',
      intersect: false,
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
          title: (items: TooltipItem<'line'>[]) =>
            points[items[0]?.dataIndex ?? 0]?.periodLabel ?? 'Half-year period',
          label: (tooltipItem: TooltipItem<'line'>) => {
            const averageScore = tooltipItem.parsed.y
            return `Average score: ${typeof averageScore === 'number' ? averageScore.toFixed(1) : '0.0'}`
          },
          footer: (items: TooltipItem<'line'>[]) => {
            const point = points[items[0]?.dataIndex ?? 0]
            if (!point) return ''
            return `${point.pilotCount} pilots • latest completed training per pilot in period`
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

export const getCompetencyAverageTrendChartMinWidth = (pointCount: number) =>
  pointCount > 6 ? Math.max(640, pointCount * 96) : undefined

export const mapPilotDistributionRows = (items: PilotGradeDistributionItem[]): DistributionRow[] =>
  items.map((item, index) => ({
    label: resolvePersonLabel(item.firstName, item.lastName, `Pilot ${index + 1}`),
    grades: item.grades.map((grade) => ({
      gradeCode: grade.gradeCode,
      gradeLabel: grade.gradeLabel,
      gradeScoreNumeric: grade.gradeScoreNumeric,
      gradeColorHex: grade.gradeColorHex,
      value: grade.gradeCount,
    })),
  }))

export const filterPilotGradeDistributionItemsByRating = ({
  items,
  topPerformersCount,
  trainingConcernCount,
}: {
  items: PilotGradeDistributionItem[]
  topPerformersCount: number | null
  trainingConcernCount: number | null
}) => {
  const normalizedTopPerformersCount = normalizeRankFilterValue(topPerformersCount)
  const normalizedTrainingConcernCount = normalizeRankFilterValue(trainingConcernCount)

  if (normalizedTopPerformersCount === null && normalizedTrainingConcernCount === null) {
    return {
      items,
      topGroupCount: 0,
      trainingConcernGroupCount: 0,
    }
  }

  const rankedPilots = items.map((item, index) => ({
    pilotId: item.pilotId,
    label: resolvePersonLabel(item.firstName, item.lastName, `Pilot ${index + 1}`),
    averageScore: resolveWeightedAverageGradeScore(item.grades),
  }))
  const itemsByPilotId = new Map(items.map((item) => [item.pilotId, item]))
  const orderedSelectedPilotIds: string[] = []
  const selectedPilotIds = new Set<string>()
  let topGroupCount = 0
  let trainingConcernGroupCount = 0

  if (normalizedTopPerformersCount !== null) {
    rankedPilots
      .slice()
      .sort((left, right) => compareRankedPilots(left, right, 'desc'))
      .slice(0, normalizedTopPerformersCount)
      .forEach((pilot) => {
        if (selectedPilotIds.has(pilot.pilotId)) return
        selectedPilotIds.add(pilot.pilotId)
        orderedSelectedPilotIds.push(pilot.pilotId)
        topGroupCount += 1
      })
  }

  if (normalizedTrainingConcernCount !== null) {
    rankedPilots
      .slice()
      .sort((left, right) => compareRankedPilots(left, right, 'asc'))
      .slice(0, normalizedTrainingConcernCount)
      .forEach((pilot) => {
        if (selectedPilotIds.has(pilot.pilotId)) return
        selectedPilotIds.add(pilot.pilotId)
        orderedSelectedPilotIds.push(pilot.pilotId)
        trainingConcernGroupCount += 1
      })
  }

  return {
    items: orderedSelectedPilotIds
      .map((pilotId) => itemsByPilotId.get(pilotId))
      .filter((item): item is PilotGradeDistributionItem => Boolean(item)),
    topGroupCount,
    trainingConcernGroupCount,
  }
}

export const filterInstructorGradeDistributionItems = ({
  items,
  scoreSpread,
  varianceMin,
  varianceMax,
  lowestGradeUsageMin,
  highestGradeUsageMin,
  extremeGradeUsageMin,
}: {
  items: InstructorGradeDistributionItem[]
  scoreSpread: InstructorScoreSpreadFilter
  varianceMin: number | null
  varianceMax: number | null
  lowestGradeUsageMin: number | null
  highestGradeUsageMin: number | null
  extremeGradeUsageMin: number | null
}) => {
  const normalizedVarianceMin = normalizeNonNegativeFilterValue(varianceMin)
  const normalizedVarianceMax = normalizeNonNegativeFilterValue(varianceMax)
  const effectiveVarianceMin =
    normalizedVarianceMin !== null && normalizedVarianceMax !== null
      ? Math.min(normalizedVarianceMin, normalizedVarianceMax)
      : normalizedVarianceMin
  const effectiveVarianceMax =
    normalizedVarianceMin !== null && normalizedVarianceMax !== null
      ? Math.max(normalizedVarianceMin, normalizedVarianceMax)
      : normalizedVarianceMax
  const effectiveLowestGradeUsageMin = normalizePercentageFilterValue(lowestGradeUsageMin)
  const effectiveHighestGradeUsageMin = normalizePercentageFilterValue(highestGradeUsageMin)
  const effectiveExtremeGradeUsageMin = normalizePercentageFilterValue(extremeGradeUsageMin)

  if (
    scoreSpread === 'all' &&
    effectiveVarianceMin === null &&
    effectiveVarianceMax === null &&
    effectiveLowestGradeUsageMin === null &&
    effectiveHighestGradeUsageMin === null &&
    effectiveExtremeGradeUsageMin === null
  ) {
    return items
  }

  const activeScores = items.flatMap((item) => collectActiveNumericScores(item.grades))
  const globalMinimumScore = activeScores.length > 0 ? Math.min(...activeScores) : null
  const globalMaximumScore = activeScores.length > 0 ? Math.max(...activeScores) : null

  return items.filter((item) => {
    const spreadBucket = resolveScoreSpreadBucket({
      grades: item.grades,
      globalMinimumScore,
      globalMaximumScore,
    })
    if (scoreSpread !== 'all' && spreadBucket !== scoreSpread) return false

    const variance = resolveWeightedVariance(item.grades)
    if (effectiveVarianceMin !== null && (variance === null || variance < effectiveVarianceMin))
      return false
    if (effectiveVarianceMax !== null && (variance === null || variance > effectiveVarianceMax))
      return false

    const { lowestGradeUsagePercent, highestGradeUsagePercent, extremeGradeUsagePercent } =
      resolveExtremeUsagePercentages({
        grades: item.grades,
        globalMinimumScore,
        globalMaximumScore,
      })

    if (
      effectiveLowestGradeUsageMin !== null &&
      (lowestGradeUsagePercent === null || lowestGradeUsagePercent < effectiveLowestGradeUsageMin)
    ) {
      return false
    }
    if (
      effectiveHighestGradeUsageMin !== null &&
      (highestGradeUsagePercent === null ||
        highestGradeUsagePercent < effectiveHighestGradeUsageMin)
    ) {
      return false
    }
    if (
      effectiveExtremeGradeUsageMin !== null &&
      (extremeGradeUsagePercent === null ||
        extremeGradeUsagePercent < effectiveExtremeGradeUsageMin)
    ) {
      return false
    }

    return true
  })
}

export const mapInstructorDistributionRows = (
  items: InstructorGradeDistributionItem[],
): DistributionRow[] =>
  items.map((item, index) => ({
    label: resolvePersonLabel(item.firstName, item.lastName, `Instructor ${index + 1}`),
    grades: item.grades.map((grade) => ({
      gradeCode: grade.gradeCode,
      gradeLabel: grade.gradeLabel,
      gradeScoreNumeric: grade.gradeScoreNumeric,
      gradeColorHex: grade.gradeColorHex,
      value: grade.gradeCount,
    })),
  }))
