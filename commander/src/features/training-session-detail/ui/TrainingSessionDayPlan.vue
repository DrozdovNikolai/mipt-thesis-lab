<script setup lang="ts">
import { computed } from 'vue'
import type {
  TrainingSessionDetailAssessment,
  TrainingSessionDetailModule,
  TrainingSessionDetailParticipant,
  TrainingSessionProjectionSource,
} from '@/entities/commander/types'
import { flattenExercises, getExerciseReportLookup } from '../lib/dayPlan'
import ExerciseCard from './ExerciseCard.vue'
const props = defineProps<{
  modules: TrainingSessionDetailModule[]
  participants: TrainingSessionDetailParticipant[]
  projectionSource: TrainingSessionProjectionSource
  selectedAssessment: TrainingSessionDetailAssessment | null
}>()
const exercises = computed(() => flattenExercises(props.modules))
const reports = computed(() => getExerciseReportLookup(props.selectedAssessment))
</script>
<template>
  <section
    class="space-y-4 rounded-[28px] border border-line bg-surface p-5 shadow-sm"
    :class="{ 'border-dashed border-line-strong': !exercises.length }"
  >
    <header class="space-y-1">
      <h2 class="text-lg font-semibold text-foreground">
        {{ exercises.length ? 'Comments and attempts' : 'Comments' }}
      </h2>
      <p class="text-sm text-foreground-secondary">
        {{
          exercises.length
            ? 'Attempt context and comments at their recorded offsets. Crew history is retained server-side.'
            : 'This session does not contain any exercises yet.'
        }}
      </p>
    </header>
    <div v-if="exercises.length" class="space-y-4">
      <ExerciseCard
        v-for="exercise in exercises"
        :key="exercise.id"
        :exercise="exercise"
        :exercise-report="reports.get(exercise.id)"
        :participants="participants"
        :projection-source="projectionSource"
        :selected-assessment="selectedAssessment"
      />
    </div>
  </section>
</template>
