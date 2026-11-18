import { describe, expect, it } from 'vitest'
import type {
  GradeDistributionBucket,
  InstructorGradeDistributionItem,
  PilotGradeDistributionItem,
} from '@/entities/commander/types'
import {
  filterInstructorGradeDistributionItems,
  filterPilotGradeDistributionItemsByRating,
} from '@/features/analytics/lib/gradeDistribution'
const grades = (scores: [number | string | null, number][]): GradeDistributionBucket[] =>
  scores.map(([gradeScoreNumeric, gradeCount], index) => ({
    gradeCode: String(index),
    gradeLabel: String(gradeScoreNumeric),
    gradeScoreNumeric,
    gradeCount,
    gradeColorHex: null,
  }))
const pilot = (
  id: string,
  scores: [number | string | null, number][],
): PilotGradeDistributionItem => ({
  pilotId: id,
  firstName: id,
  lastName: null,
  assessedGradeCount: 100,
  grades: grades(scores),
})
const instructor = (
  id: string,
  scores: [number | string | null, number][],
): InstructorGradeDistributionItem => ({
  instructorId: id,
  firstName: id,
  lastName: null,
  assessedGradeCount: 100,
  grades: grades(scores),
})
const noFilters = {
  scoreSpread: 'all' as const,
  varianceMin: null,
  varianceMax: null,
  lowestGradeUsageMin: null,
  highestGradeUsageMin: null,
  extremeGradeUsageMin: null,
}

describe('independent analytics expectations', () => {
  it('ranks weighted averages and deduplicates overlapping top/bottom groups', () => {
    const result = filterPilotGradeDistributionItemsByRating({
      items: [
        pilot('a', [
          [1, 1],
          [5, 3],
        ]),
        pilot('b', [[3, 4]]),
        pilot('c', [
          [1, 3],
          [5, 1],
        ]),
      ],
      topPerformersCount: 2,
      trainingConcernCount: 2,
    })
    expect(result.items.map((item) => item.pilotId)).toEqual(['a', 'b', 'c']) // Means 4, 3, 2.
    expect([result.topGroupCount, result.trainingConcernGroupCount]).toEqual([2, 1])
  })
  it('uses stable name/id tie breaking, and does not interpret missing grades as zero', () => {
    const result = filterPilotGradeDistributionItemsByRating({
      items: [
        pilot('missing', [
          [null, 99],
          ['bad', 10],
        ]),
        pilot('b', [[2, 5]]),
        pilot('a', [[2, 1]]),
      ],
      topPerformersCount: 3,
      trainingConcernCount: null,
    })
    expect(result.items.map((item) => item.pilotId)).toEqual(['a', 'b', 'missing'])
  })
  it('computes population variance from counts and accepts reversed bounds', () => {
    const items = [
      instructor('variance3', [
        [1, 1],
        [5, 3],
      ]),
      instructor('variance0', [[3, 4]]),
      instructor('missing', [[null, 20]]),
    ]
    const result = filterInstructorGradeDistributionItems({
      items,
      ...noFilters,
      varianceMin: 3.01,
      varianceMax: 2.99,
    })
    expect(result.map((item) => item.instructorId)).toEqual(['variance3']) // Mean 4, variance (9 + 3)/4 = 3.
  })
  it('uses the observed global scale for spread and extreme usage percentages', () => {
    const items = [
      instructor('mixed', [
        [1, 1],
        [5, 3],
      ]),
      instructor('middle', [[3, 4]]),
      instructor('low', [[1, 4]]),
    ]
    expect(
      filterInstructorGradeDistributionItems({ items, ...noFilters, scoreSpread: 'high' }).map(
        (item) => item.instructorId,
      ),
    ).toEqual(['mixed'])
    expect(
      filterInstructorGradeDistributionItems({ items, ...noFilters, highestGradeUsageMin: 75 }).map(
        (item) => item.instructorId,
      ),
    ).toEqual(['mixed'])
    expect(
      filterInstructorGradeDistributionItems({ items, ...noFilters, lowestGradeUsageMin: 25 }).map(
        (item) => item.instructorId,
      ),
    ).toEqual(['mixed', 'low'])
    expect(
      filterInstructorGradeDistributionItems({
        items,
        ...noFilters,
        extremeGradeUsageMin: 100,
      }).map((item) => item.instructorId),
    ).toEqual(['mixed', 'low'])
  })
})
