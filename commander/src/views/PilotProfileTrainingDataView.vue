<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { useQuery } from '@tanstack/vue-query'
import { commanderApi } from '@/entities/commander/api'
import { commanderKeys } from '@/entities/commander/queryKeys'
import { useSessionScope } from '@/entities/session/useSessionScope'
import PilotTrainingSnapshot from '@/features/pilot-profile/ui/PilotTrainingSnapshot.vue'
import TrainingSessionsList from '@/features/training-sessions/ui/TrainingSessionsList.vue'
import { getErrorMessage } from '@/shared/lib/errorMessage'
const route = useRoute(),
  scope = useSessionScope()
const pilotId = computed(() => String(route.params.pilotId ?? ''))
const summaryQuery = useQuery({
  queryKey: computed(() => [
    ...commanderKeys.root(scope.value),
    'pilot',
    pilotId.value,
    'training-summary',
  ]),
  queryFn: ({ signal }) => commanderApi.getPilotTrainingSummary(pilotId.value, signal),
  enabled: computed(() => Boolean(pilotId.value)),
  retry: 0,
})
const aircraft = useQuery({
  queryKey: computed(() => commanderKeys.aircraft(scope.value)),
  queryFn: ({ signal }) => commanderApi.listAircraft(signal),
  retry: 0,
})
const flightTypes = useQuery({
  queryKey: computed(() => commanderKeys.flightTypes(scope.value)),
  queryFn: () => commanderApi.listFlightTypes(),
  retry: 0,
})
const summary = summaryQuery.data
const labels = computed(() =>
  Object.fromEntries((aircraft.data.value ?? []).map((item) => [item.id, item.code])),
)
const colors = computed(() =>
  Object.fromEntries((aircraft.data.value ?? []).map((item) => [item.id, item.colorHex])),
)
const thresholds = computed(
  () => flightTypes.data.value?.find((item) => item.isMain)?.thresholds ?? [],
)
const warnings = computed(() =>
  [
    aircraft.isError.value
      ? getErrorMessage(aircraft.error.value, 'Failed to load aircraft lookup.')
      : null,
    flightTypes.isError.value
      ? getErrorMessage(flightTypes.error.value, 'Failed to load main threshold lookup.')
      : null,
  ].filter((warning): warning is string => Boolean(warning)),
)
</script>
<template>
  <section
    v-if="!pilotId || summaryQuery.isError.value"
    role="alert"
    class="rounded-2xl border border-line-danger bg-danger-soft px-4 py-3 text-sm text-danger"
  >
    {{
      !pilotId
        ? 'Pilot id is missing.'
        : getErrorMessage(summaryQuery.error.value, 'Failed to load pilot training data.')
    }}
  </section>
  <section v-else-if="!summary" class="space-y-4" aria-label="Loading pilot training data">
    <div
      v-for="index in 2"
      :key="index"
      class="h-80 animate-pulse rounded-[32px] bg-surface-muted"
    />
    <TrainingSessionsList
      :aircraft-labels-by-id="{}"
      :aircraft-colors-by-id="{}"
      is-loading
      :sessions="[]"
    />
  </section>
  <section v-else class="space-y-4">
    <PilotTrainingSnapshot
      :rating="summary.pilot.rating"
      :latest-training="summary.latestCompletedTraining"
      :competence-histories="summary.competenceHistories"
      :main-thresholds="thresholds"
      :position-average-grades="summary.positionAverageGrades"
    />
    <section
      v-for="warning in warnings"
      :key="warning"
      class="rounded-2xl border border-line-warning bg-warning-soft px-4 py-3 text-sm text-warning"
    >
      {{ warning }}
    </section>
    <section class="space-y-3">
      <header class="space-y-1">
        <h2 class="text-lg font-semibold text-foreground">Completed training sessions</h2>
        <p class="text-sm text-foreground-secondary">
          Grouped by scenario and crew for this pilot, newest first.
        </p>
      </header>
      <TrainingSessionsList
        :aircraft-labels-by-id="labels"
        :aircraft-colors-by-id="colors"
        :is-loading="false"
        :sessions="summary.completedTrainingSessions"
      />
    </section>
  </section>
</template>
