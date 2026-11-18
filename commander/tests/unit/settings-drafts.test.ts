import { describe, expect, it } from 'vitest'
import { competences, initialTypes, threshold } from '../fixtures/mockApi'
import {
  buildThresholdsReplacePayload,
  createFlightTypeDraft,
  normalizeFlightTypeName,
  pruneFlightTypeDraft,
  sortFlightTypesByName,
} from '@/features/settings/lib/flightTypeDrafts'
import {
  clampFlightTypeNameInput,
  sanitizeFlightTypeThresholdInput,
} from '@/features/settings/lib/settingsConstraints'

describe('settings payload contracts', () => {
  it('normalizes whitespace and limits names to 100 input characters', () => {
    expect(normalizeFlightTypeName('  Line\n  check\t A  ')).toBe('Line check A')
    expect(clampFlightTypeNameInput('A'.repeat(101))).toHaveLength(100)
  })
  it.each([
    ['', ''],
    ['0.', '0.'],
    ['.25', '0.25'],
    ['999999.99999', '999999.9999'],
    ['1234567', '123456'],
    ['-3', ''],
    ['2e3', '2'],
  ])('retains the documented editable prefix %s', (input, expected) => {
    expect(sanitizeFlightTypeThresholdInput(input)).toBe(expected)
  })
  it('distinguishes clearing from zero and serializes the full competence set', () => {
    expect(buildThresholdsReplacePayload(competences, { 1: '', 2: '0.' })).toEqual({
      payload: { thresholds: [{ competenceId: 2, value: '0' }] },
      validationMessage: null,
    })
    expect(
      buildThresholdsReplacePayload(competences, { 1: '2.1250', 2: '999999.9999' }).payload,
    ).toEqual({
      thresholds: [
        { competenceId: 1, value: '2.125' },
        { competenceId: 2, value: '999999.9999' },
      ],
    })
  })
  it.each(['-1', 'NaN', 'Infinity', '1000000', '1.00001', '.'])(
    'rejects invalid persisted values %s instead of sending a partial replace',
    (value) => {
      const result = buildThresholdsReplacePayload(competences, { 1: value, 2: '2' })
      expect(result.payload).toBeNull()
      expect(result.validationMessage).toContain('OPS')
    },
  )
  it('prunes only a completely saved draft and retains the independently edited part', () => {
    const type = initialTypes()[0]!
    const draft = createFlightTypeDraft(type)
    draft.name = 'Local name'
    draft.thresholds[1] = '4'
    const renamed = { ...type, name: 'Local name' }
    expect(pruneFlightTypeDraft(renamed, draft, competences)?.thresholds[1]).toBe('4')
    const thresholdsSaved = { ...type, thresholds: [threshold(1, '4'), threshold(2, '6')] }
    expect(pruneFlightTypeDraft(thresholdsSaved, draft, competences)?.name).toBe('Local name')
    expect(
      pruneFlightTypeDraft({ ...thresholdsSaved, name: 'Local name' }, draft, competences),
    ).toBeNull()
  })
  it('places main first, then sorts names, leaving input order untouched', () => {
    const types = initialTypes().reverse()
    expect(sortFlightTypesByName(types).map((type) => type.id)).toEqual([1, 2])
    expect(types.map((type) => type.id)).toEqual([2, 1])
  })
})
