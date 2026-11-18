<script setup lang="ts">
import type { InstructorScoreSpreadFilter } from '../lib/gradeDistribution'
const spread = defineModel<InstructorScoreSpreadFilter>('scoreSpread', { required: true })
const varianceMin = defineModel<number | null>('varianceMin', { required: true })
const varianceMax = defineModel<number | null>('varianceMax', { required: true })
const lowestGradeUsageMin = defineModel<number | null>('lowestGradeUsageMin', { required: true })
const highestGradeUsageMin = defineModel<number | null>('highestGradeUsageMin', { required: true })
const extremeGradeUsageMin = defineModel<number | null>('extremeGradeUsageMin', { required: true })
const fields = [
  { label: 'Variance min', model: varianceMin, step: 0.01, max: undefined },
  { label: 'Variance max', model: varianceMax, step: 0.01, max: undefined },
  { label: '% of 1 min', model: lowestGradeUsageMin, step: 1, max: 100 },
  { label: '% of 5 min', model: highestGradeUsageMin, step: 1, max: 100 },
  { label: '% of 1 + 5 min', model: extremeGradeUsageMin, step: 1, max: 100 },
]
function parse(event: Event) {
  const value = (event.target as HTMLInputElement).value
  const n = Number(value)
  return value && Number.isFinite(n) && n >= 0 ? n : null
}
const fieldClass =
  'h-9 rounded-xl border border-line bg-surface px-3 text-sm text-foreground outline-none transition focus:border-line-emphasis focus:ring-2 focus:ring-focus'
</script>
<template>
  <section
    class="grid gap-2 rounded-2xl border border-line bg-surface p-3 grid-cols-[repeat(auto-fit,minmax(min(100%,180px),1fr))]"
  >
    <div class="w-full">
      <select v-model="spread" aria-label="Score spread" :class="[fieldClass, 'w-full']">
        <option value="all">All spreads</option>
        <option value="low">Low spread</option>
        <option value="medium">Medium spread</option>
        <option value="high">High spread</option>
      </select>
    </div>
    <label
      v-for="field in fields"
      :key="field.label"
      class="flex min-w-0 w-full items-center gap-1.5"
      ><span
        class="shrink-0 whitespace-nowrap text-xs font-semibold tracking-wide text-foreground"
        >{{ field.label }}</span
      ><input
        type="number"
        :inputmode="field.step === 1 ? 'numeric' : 'decimal'"
        :min="0"
        :max="field.max"
        :step="field.step"
        :value="field.model.value ?? ''"
        :class="[fieldClass, 'min-w-0 flex-1 px-2 text-right']"
        @input="field.model.value = parse($event)"
    /></label>
  </section>
</template>
