<script setup lang="ts">
import { computed, ref } from 'vue'
import type {
  CommanderFlightTypeThreshold,
  PilotCompetenceGradeHistory,
  PilotLatestCompletedTraining,
  PilotPositionAverageCompetenceGrade,
} from '@/entities/commander/types'
import {
  createCompetenceHistoryChartData,
  createCompetenceHistoryChartOptions,
  createPilotRadarChartData,
  createPilotRadarChartOptions,
  getCompetenceHistoryChartMinWidth,
  getLatestCompetenceGradeCode,
  HISTORY_LINE_COLOR,
  POSITION_AVERAGE_RADAR_COLOR,
  RADAR_BORDER_COLOR,
  THRESHOLD_HISTORY_LINE_COLOR,
  THRESHOLD_RADAR_COLOR,
} from '../lib/trainingDataCharts'
import { formatTrainingDurationMs } from '@/features/training-session-detail/lib/crewTimelinePresentation'
import ChartLegend from '@/shared/ui/charts/ChartLegend.vue'
import LineChart from '@/shared/ui/charts/LineChart.vue'
import RadarChart from '@/shared/ui/charts/RadarChart.vue'
const props = defineProps<{
  rating: string | null
  latestTraining: PilotLatestCompletedTraining | null
  competenceHistories: PilotCompetenceGradeHistory[]
  mainThresholds: CommanderFlightTypeThreshold[]
  positionAverageGrades: PilotPositionAverageCompetenceGrade[]
}>()
const latestGrades = computed(() =>
  [...(props.latestTraining?.grades ?? [])].sort(
    (a, b) => a.orderIndex - b.orderIndex || a.competenceId - b.competenceId,
  ),
)
const selectedId = ref<number | null>(null)
const selected = computed(() => {
  const id =
    selectedId.value !== null &&
    props.competenceHistories.some((item) => item.competenceId === selectedId.value)
      ? selectedId.value
      : (latestGrades.value[0]?.competenceId ?? props.competenceHistories[0]?.competenceId ?? null)
  return (
    props.competenceHistories.find((item) => item.competenceId === id) ??
    props.competenceHistories[0] ??
    null
  )
})
const threshold = computed(() => {
  const found = props.mainThresholds.find(
    (item) => item.competenceId === selected.value?.competenceId,
  )
  if (!found) return null
  const value = Number(found.value)
  return Number.isFinite(value) ? value : null
})
const radarData = computed(() =>
  createPilotRadarChartData(latestGrades.value, props.mainThresholds, props.positionAverageGrades),
)
const radarOptions = computed(() =>
  createPilotRadarChartOptions(
    latestGrades.value,
    props.mainThresholds,
    props.positionAverageGrades,
  ),
)
const historyData = computed(() =>
  createCompetenceHistoryChartData(selected.value?.history ?? [], threshold.value),
)
const historyOptions = computed(() =>
  createCompetenceHistoryChartOptions(selected.value?.history ?? [], threshold.value),
)
const radarLegend = computed(() => [
  { label: 'Latest training', color: RADAR_BORDER_COLOR },
  ...(props.mainThresholds.length
    ? [{ label: 'Main threshold', color: THRESHOLD_RADAR_COLOR }]
    : []),
  ...(props.positionAverageGrades.length
    ? [{ label: 'Same-position average', color: POSITION_AVERAGE_RADAR_COLOR }]
    : []),
])
const historyLegend = computed(() => [
  { label: 'Score', color: HISTORY_LINE_COLOR },
  ...(threshold.value !== null
    ? [{ label: 'Main threshold', color: THRESHOLD_HISTORY_LINE_COLOR }]
    : []),
])
const formatTimestamp = (value: string) =>
  new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(
    new Date(value),
  )
const roleLabel = (value: string | null) =>
  value === 'cm1' ? 'CM 1' : value === 'cm2' ? 'CM 2' : '—'
const summaryRole = (training: PilotLatestCompletedTraining) =>
  training.roleProjectionSource === 'ACTUAL_TIMELINE'
    ? `Current at completion ${training.finalCrewSlot ?? roleLabel(training.trainingRole).replace(' ', '')}`
    : `${roleLabel(training.trainingRole)} • Legacy planned roles`
const tabClass = (active: boolean) => [
  'inline-flex h-[29px] w-[139px] items-center justify-between rounded-[14px] border bg-surface px-3 text-xs font-semibold text-foreground',
  active ? 'border-[#212121]' : 'border-transparent transition hover:border-line',
]
</script>
<template>
  <section class="rounded-[32px] border border-line bg-surface p-5 shadow-sm">
    <header class="mb-5 flex flex-wrap items-start justify-between gap-3">
      <div>
        <h2 class="text-lg font-semibold text-foreground">Training snapshot</h2>
        <p class="mt-1 text-sm text-foreground-secondary">
          {{
            latestTraining
              ? `${latestTraining.title} • ${formatTimestamp(latestTraining.completedAt)} • ${summaryRole(latestTraining)}`
              : 'Latest completed training grades and per-competence history.'
          }}
        </p>
      </div>
      <div v-if="latestTraining" class="flex flex-wrap justify-end gap-2">
        <span
          class="inline-flex items-center rounded-full border border-line bg-surface-muted px-3 py-1.5 text-xs font-semibold text-foreground"
          >{{
            latestTraining.roleProjectionSource === 'ACTUAL_TIMELINE'
              ? `Current ${latestTraining.finalCrewSlot ?? roleLabel(latestTraining.trainingRole).replace(' ', '')}`
              : roleLabel(latestTraining.trainingRole)
          }}</span
        ><template v-if="latestTraining.roleProjectionSource === 'ACTUAL_TIMELINE'"
          ><span
            class="inline-flex items-center rounded-full border border-[#284692]/30 bg-[#284692]/10 px-3 py-1.5 text-xs font-semibold text-[#284692]"
            >PF {{ formatTrainingDurationMs(latestTraining.pfDurationMs ?? 0) }}</span
          ><span
            class="inline-flex items-center rounded-full border border-[#1D9634]/30 bg-[#1D9634]/10 px-3 py-1.5 text-xs font-semibold text-[#1D7A31]"
            >PM {{ formatTrainingDurationMs(latestTraining.pmDurationMs ?? 0) }}</span
          ></template
        >
      </div>
    </header>
    <div
      class="grid min-w-0 gap-6 xl:grid-cols-[250px_139px_minmax(0,1fr)] xl:grid-rows-[auto_minmax(0,1fr)] xl:items-start"
    >
      <aside class="order-1 flex min-w-0 justify-end xl:col-start-3 xl:row-start-1">
        <div class="flex flex-col items-center gap-3">
          <div
            class="flex h-[70px] w-[70px] flex-col items-center justify-center rounded-full border border-line bg-surface-pilot-badge text-foreground-pilot-badge shadow-sm"
          >
            <span class="text-xl font-semibold leading-none">{{ rating ?? '—' }}</span
            ><span class="mt-1 text-[9px] font-semibold uppercase tracking-[0.14em] leading-none"
              >Rating</span
            >
          </div>
        </div>
      </aside>
      <section class="order-2 min-w-0 space-y-3 xl:col-start-1 xl:row-span-2">
        <div><h3 class="text-base font-semibold text-foreground">Latest training radar</h3></div>
        <ChartLegend :items="radarLegend" />
        <div v-if="latestGrades.length" class="mx-auto w-full max-w-[250px]">
          <RadarChart
            ariaLabel="Latest pilot competence radar chart"
            :data="radarData"
            :options="radarOptions"
            :height="250"
          />
        </div>
        <div
          v-else
          class="flex h-[250px] items-center justify-center rounded-[24px] border border-dashed border-line-strong px-5 text-center text-sm text-foreground-secondary"
        >
          No completed training grades are available for the radar chart yet.
        </div>
      </section>
      <section class="order-3 min-w-0 xl:col-start-2 xl:row-span-2 xl:self-center">
        <div v-if="competenceHistories.length" class="space-y-2">
          <button
            v-for="competence in competenceHistories"
            :key="competence.competenceId"
            type="button"
            :class="tabClass(competence.competenceId === selected?.competenceId)"
            @click="selectedId = competence.competenceId"
          >
            <span>{{ competence.competenceCode }}</span
            ><span>{{
              getLatestCompetenceGradeCode(
                competence.competenceId,
                latestGrades,
                competence.history,
              )
            }}</span>
          </button>
        </div>
      </section>
      <section class="order-4 min-w-0 space-y-4 xl:col-start-3 xl:row-start-2">
        <div>
          <h3 class="text-base font-semibold text-foreground">Competence history</h3>
          <p class="mt-1 text-sm text-foreground-secondary">
            Select a competence to inspect how its score changed over completed training sessions.
          </p>
        </div>
        <div v-if="selected" class="min-w-0 space-y-3">
          <div class="flex flex-wrap items-center justify-between gap-3">
            <div>
              <p class="text-sm font-semibold text-foreground">{{ selected.competenceName }}</p>
            </div>
            <span
              class="text-xs font-semibold uppercase tracking-[0.16em] text-foreground-secondary"
              >{{ selected.history.length }} sessions</span
            >
          </div>
          <ChartLegend :items="historyLegend" /><LineChart
            :ariaLabel="`${selected.competenceName} score history chart`"
            :data="historyData"
            :options="historyOptions"
            :min-width="getCompetenceHistoryChartMinWidth(selected.history.length)"
            surface-class-name="bg-white"
          />
        </div>
        <div
          v-else
          class="rounded-[24px] border border-dashed border-line-strong px-5 py-10 text-center text-sm text-foreground-secondary"
        >
          No competence history is available yet.
        </div>
      </section>
    </div>
  </section>
</template>
