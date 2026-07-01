<script setup lang="ts">
import { computed, ref } from 'vue'
import type {
  TrainingSessionDetailAssessment,
  TrainingSessionDetailAssessmentExerciseReport,
  TrainingSessionDetailExercise,
  TrainingSessionDetailParticipant,
  TrainingSessionProjectionSource,
} from '@/entities/commander/types'
import {
  getExerciseDisplayLabel,
  getExerciseEmptyStateText,
  getExercisePilotRoleMeta,
  getParticipantName,
  getRunRemarks,
} from '../lib/dayPlan'
import { formatTrainingDurationMs } from '../lib/crewTimelinePresentation'
import RemarkCard from './RemarkCard.vue'
const props = defineProps<{
  exercise: TrainingSessionDetailExercise
  exerciseReport?: TrainingSessionDetailAssessmentExerciseReport
  participants: TrainingSessionDetailParticipant[]
  projectionSource: TrainingSessionProjectionSource
  selectedAssessment: TrainingSessionDetailAssessment | null
}>()
const runs = computed(() =>
  [...(props.exercise.runs ?? [])].sort((a, b) => a.runIndex - b.runIndex),
)
const selectedRunKey = ref(runs.value.at(-1)?.exerciseSessionKey ?? '')
const selectedRun = computed(
  () =>
    runs.value.find((run) => run.exerciseSessionKey === selectedRunKey.value) ??
    runs.value.at(-1) ??
    null,
)
const remarks = computed(() =>
  getRunRemarks(props.exerciseReport?.remarks ?? [], selectedRun.value),
)
const legacyRole = computed(() =>
  props.projectionSource === 'LEGACY_PLANNED'
    ? getExercisePilotRoleMeta(props.exercise.crewMemberNumber, props.selectedAssessment)
    : null,
)
const label = computed(() => getExerciseDisplayLabel(props.exercise))
const individualName = computed(() =>
  getParticipantName(props.exercise.resolvedForAssessmentId, props.participants),
)
const elements = computed(() =>
  [...props.exercise.elements].sort((a, b) => a.orderIndex - b.orderIndex || a.id - b.id),
)
</script>
<template>
  <article class="rounded-2xl border border-line bg-surface-muted px-4 py-4">
    <div class="grid gap-4 lg:grid-cols-[260px_minmax(0,1fr)]">
      <div class="space-y-4">
        <div class="space-y-2">
          <p
            class="text-[11px] font-semibold uppercase tracking-[0.16em] text-foreground-secondary"
          >
            {{ label }}
          </p>
          <p v-if="individualName" class="text-xs font-semibold text-foreground">
            Individual exercise for {{ individualName }}
          </p>
          <p v-if="legacyRole" class="text-sm font-semibold" :style="{ color: legacyRole.color }">
            {{ legacyRole.label }}
          </p>
        </div>
        <section class="space-y-2">
          <ul v-if="elements.length" class="space-y-1.5">
            <li
              v-for="element in elements"
              :key="element.id"
              class="text-sm font-semibold text-foreground"
            >
              {{ element.elementName }}
            </li>
          </ul>
          <div
            v-else
            class="rounded-xl border border-dashed border-line-strong px-4 py-6 text-sm text-foreground-secondary"
          >
            {{ getExerciseEmptyStateText(exercise) }}
          </div>
        </section>
      </div>
      <div class="space-y-4 border-t border-line pt-4 lg:border-t-0 lg:border-l lg:pt-0 lg:pl-4">
        <section
          v-if="selectedRun"
          class="space-y-3"
          :aria-labelledby="`attempt-heading-${exercise.id}`"
        >
          <div class="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h4
                :id="`attempt-heading-${exercise.id}`"
                class="text-sm font-semibold text-foreground"
              >
                Attempt details
              </h4>
              <p class="mt-1 text-xs text-foreground-secondary">
                Attempt {{ selectedRun.runIndex }} · {{ selectedRun.status.toLowerCase() }}
              </p>
            </div>
            <label
              v-if="runs.length > 1"
              class="flex items-center gap-2 text-xs font-semibold text-foreground-secondary"
              >Attempt<select
                :aria-label="`${label} attempt`"
                :value="selectedRun.exerciseSessionKey"
                class="h-9 rounded-xl border border-line bg-surface px-2 text-xs text-foreground outline-none focus:border-line-emphasis focus:ring-2 focus:ring-focus"
                @change="selectedRunKey = ($event.target as HTMLSelectElement).value"
              >
                <option
                  v-for="run in runs"
                  :key="run.exerciseSessionKey"
                  :value="run.exerciseSessionKey"
                >
                  {{ run.runIndex }} · {{ run.status.toLowerCase() }}
                </option>
              </select></label
            >
          </div>
          <div class="flex flex-wrap gap-2 text-xs font-semibold">
            <span class="rounded-full border border-line bg-surface px-2.5 py-1 text-foreground"
              >Active {{ formatTrainingDurationMs(selectedRun.activeDurationMs) }}</span
            >
          </div>
        </section>
        <section class="space-y-3 border-t border-line pt-4">
          <div class="flex items-center justify-between gap-3">
            <h4 class="text-sm font-semibold text-foreground">Comments</h4>
            <span v-if="selectedRun" class="text-xs text-foreground-secondary"
              >Attempt {{ selectedRun.runIndex }}</span
            >
          </div>
          <div v-if="remarks.length" class="space-y-3">
            <RemarkCard
              v-for="remark in remarks"
              :key="remark.clientReportId ?? remark.id"
              :remark="remark"
              :projection-source="projectionSource"
            />
          </div>
          <div
            v-else
            class="rounded-xl border border-dashed border-line-strong px-4 py-6 text-sm text-foreground-secondary"
          >
            {{
              selectedAssessment
                ? 'No remarks were linked to this attempt for the selected participant assessment.'
                : 'Choose a participant assessment to inspect exercise remarks.'
            }}
          </div>
        </section>
      </div>
    </div>
  </article>
</template>
