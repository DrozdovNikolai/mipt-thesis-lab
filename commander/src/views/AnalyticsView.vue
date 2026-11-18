<script setup lang="ts">
import { computed, reactive, ref, shallowRef, watch } from 'vue'
import { keepPreviousData, useQuery } from '@tanstack/vue-query'
import type { CommanderAnalyticsQuery } from '@/entities/commander/types'
import { commanderApi } from '@/entities/commander/api'
import { commanderKeys } from '@/entities/commander/queryKeys'
import type { SessionUser } from '@/entities/session/types'
import { useSessionStore } from '@/entities/session/store'
import { useSessionScope } from '@/entities/session/useSessionScope'
import { trainingApi } from '@/entities/training/api'
import { positionsApi } from '@/entities/users/api'
import { getErrorMessage } from '@/shared/lib/errorMessage'
import { useDebouncedValue } from '@/shared/lib/useDebouncedValue'
import BarChart from '@/shared/ui/charts/BarChart.vue'
import LineChart from '@/shared/ui/charts/LineChart.vue'
import type { AutocompleteOption } from '@/shared/ui/inputs/autocomplete'
import {
  buildGradeDistributionChartData,
  createCompetencyAverageTrendChartData,
  createCompetencyAverageTrendChartOptions,
  createGradeDistributionChartOptions,
  filterPilotGradeDistributionItemsByRating,
  filterInstructorGradeDistributionItems,
  getCompetencyAverageTrendChartMinWidth,
  getGradeDistributionChartMinWidth,
  getHorizontalGradeDistributionChartHeight,
  type InstructorScoreSpreadFilter,
  mapCompetencyDistributionRows,
  mapInstructorDistributionRows,
  mapPilotDistributionRows,
} from '@/features/analytics/lib/gradeDistribution'
import AnalyticsChartCard from '@/features/analytics/ui/AnalyticsChartCard.vue'
import CompetencyTrendFilters from '@/features/analytics/ui/CompetencyTrendFilters.vue'
import AnalyticsFilters from '@/features/analytics/ui/AnalyticsFilters.vue'
import InstructorAssessmentFilters from '@/features/analytics/ui/InstructorAssessmentFilters.vue'
import PilotPerformanceFilters from '@/features/analytics/ui/PilotPerformanceFilters.vue'
const session = useSessionStore(),
  scope = useSessionScope()
const aircraftId = ref<number | null>(null),
  positionId = ref<number | null>(null),
  ageFrom = ref<number | null>(null),
  ageTo = ref<number | null>(null)
const appliedAges = ref<{ from: number | null; to: number | null }>({ from: null, to: null })
const date = ref(''),
  pilotSearch = ref(''),
  selectedPilot = shallowRef<SessionUser | null>(null)
const selectedTrendId = ref<number | null>(null),
  topCount = ref<number | null>(null),
  concernCount = ref<number | null>(null)
const defaultInstructorFilters = () => ({
  scoreSpread: 'all' as InstructorScoreSpreadFilter,
  varianceMin: null as number | null,
  varianceMax: null as number | null,
  lowestGradeUsageMin: null as number | null,
  highestGradeUsageMin: null as number | null,
  extremeGradeUsageMin: null as number | null,
})
const instructorFilters = reactive(defaultInstructorFilters())
const search = useDebouncedValue(pilotSearch, 250)
const hasAirline = computed(() => session.isReady && typeof session.user?.airlineId === 'number')
const aircraft = useQuery({
  queryKey: computed(() => ['training', ...scope.value, 'aircraft']),
  queryFn: () => trainingApi.aircraft.list(session.user?.airlineId ?? undefined),
  enabled: hasAirline,
  retry: 0,
})
const positions = useQuery({
  queryKey: computed(() => ['users', ...scope.value, 'positions']),
  queryFn: () => positionsApi.list(),
  enabled: hasAirline,
  retry: 0,
})
const pilots = useQuery({
  queryKey: computed(() => [
    ...commanderKeys.root(scope.value),
    'analytics',
    'pilot-autocomplete',
    search.value.trim().toLowerCase(),
  ]),
  queryFn: ({ signal }) =>
    commanderApi.listPilots(
      { q: search.value.trim() || undefined, sort: 'lastNameAsc', limit: 10 },
      signal,
    ),
  enabled: computed(() => session.isReady),
  placeholderData: keepPreviousData,
  retry: 0,
})
const ageError = computed(() =>
  ageFrom.value !== null && ageTo.value !== null && ageFrom.value > ageTo.value
    ? 'Age from must be less than or equal to age to. Analytics stay on the last valid age range until this is fixed.'
    : null,
)
watch([ageFrom, ageTo], ([from, to]) => {
  if (!ageError.value) appliedAges.value = { from, to }
})
const filters = computed(() => ({
  aircraftId: aircraftId.value ?? undefined,
  pilotId: selectedPilot.value?.id,
  positionId: positionId.value ?? undefined,
  ageFromYears: appliedAges.value.from ?? undefined,
  ageToYears: appliedAges.value.to ?? undefined,
  asOfDate: date.value || undefined,
}))
function analyticsQuery<T>(
  name: string,
  request: (query: CommanderAnalyticsQuery, signal?: AbortSignal) => Promise<T>,
) {
  return useQuery({
    queryKey: computed(() => [
      ...commanderKeys.root(scope.value),
      'analytics',
      name,
      filters.value,
    ]),
    queryFn: ({ signal }) => request(filters.value, signal),
    enabled: computed(() => session.isReady),
    placeholderData: keepPreviousData,
    retry: 0,
  })
}
const competencies = analyticsQuery(
  'competencies',
  commanderApi.analytics.getCompetencyGradeDistribution,
)
const trend = analyticsQuery('average-trend', commanderApi.analytics.getCompetencyAverageTrend)
const pilotGrades = analyticsQuery('pilots', commanderApi.analytics.getPilotGradeDistribution)
const instructorGrades = analyticsQuery(
  'instructors',
  commanderApi.analytics.getInstructorGradeDistribution,
)
const aircraftOptions = computed(() =>
  (aircraft.data.value ?? []).map((item) => ({ id: item.id, label: item.code })),
)
const positionOptions = computed(() =>
  (positions.data.value ?? []).map((item) => ({ id: item.id, label: item.name })),
)
const personName = (pilot: SessionUser) =>
  [pilot.firstName?.trim(), pilot.lastName?.trim()].filter(Boolean).join(' ').trim() ||
  pilot.login ||
  pilot.email
const pilotOptions = computed(() =>
  (pilots.data.value?.items ?? []).map((pilot) => ({
    value: pilot.id,
    label: personName(pilot),
    description: pilot.email,
    meta: pilot.position,
    pilot,
  })),
)
const competencyRows = computed(() =>
  mapCompetencyDistributionRows(competencies.data.value?.items ?? []),
)
const trendOptions = computed(() =>
  (trend.data.value?.items ?? []).map((item) => ({
    id: item.competenceId,
    label: item.competenceName?.trim()
      ? `${item.competenceCode} - ${item.competenceName}`
      : item.competenceCode,
  })),
)
const trendItem = computed(
  () =>
    trend.data.value?.items.find((item) => item.competenceId === selectedTrendId.value) ??
    trend.data.value?.items[0] ??
    null,
)
const trendSelected = computed({
  get: () => trendItem.value?.competenceId ?? null,
  set: (id: number | null) => {
    selectedTrendId.value = id
  },
})
const filteredPilots = computed(() =>
  filterPilotGradeDistributionItemsByRating({
    items: pilotGrades.data.value?.items ?? [],
    topPerformersCount: topCount.value,
    trainingConcernCount: concernCount.value,
  }),
)
const pilotRows = computed(() => mapPilotDistributionRows(filteredPilots.value.items))
const separator = computed(() =>
  filteredPilots.value.topGroupCount > 0 && filteredPilots.value.trainingConcernGroupCount > 0
    ? filteredPilots.value.topGroupCount - 1
    : null,
)
const filteredInstructors = computed(() =>
  filterInstructorGradeDistributionItems({
    items: instructorGrades.data.value?.items ?? [],
    ...instructorFilters,
  }),
)
const instructorRows = computed(() => mapInstructorDistributionRows(filteredInstructors.value))
const competencyData = computed(() => buildGradeDistributionChartData(competencyRows.value))
const trendData = computed(() => createCompetencyAverageTrendChartData(trendItem.value))
const trendChartOptions = computed(() => createCompetencyAverageTrendChartOptions(trendItem.value))
const pilotData = computed(() => buildGradeDistributionChartData(pilotRows.value))
const instructorData = computed(() => buildGradeDistributionChartData(instructorRows.value))
const verticalOptions = createGradeDistributionChartOptions(),
  horizontalOptions = createGradeDistributionChartOptions({ indexAxis: 'y' })
const error = (value: unknown) => getErrorMessage(value, 'Failed to load analytics.')
const lookupError = computed(() =>
  [
    aircraft.isError.value ? error(aircraft.error.value) : null,
    pilots.isError.value ? error(pilots.error.value) : null,
    positions.isError.value ? error(positions.error.value) : null,
  ]
    .filter(Boolean)
    .join(' '),
)
const countLabel = (shown: number, total: number, label: string) =>
  shown === total ? `${total} ${label}` : `${shown} of ${total} ${label}`
function changePilot(value: string) {
  pilotSearch.value = value
  if (selectedPilot.value && value !== personName(selectedPilot.value)) selectedPilot.value = null
}
function selectPilot(option: AutocompleteOption) {
  const found = pilotOptions.value.find((item) => item.value === option.value)
  if (found) {
    selectedPilot.value = found.pilot
    pilotSearch.value = found.label
  }
}
function reset() {
  aircraftId.value = null
  positionId.value = null
  ageFrom.value = null
  ageTo.value = null
  appliedAges.value = { from: null, to: null }
  date.value = ''
  pilotSearch.value = ''
  selectedPilot.value = null
  selectedTrendId.value = null
  topCount.value = null
  concernCount.value = null
  Object.assign(instructorFilters, defaultInstructorFilters())
}
</script>
<template>
  <section class="flex flex-col gap-4">
    <header class="space-y-1">
      <h1 class="text-2xl font-semibold tracking-tight text-foreground">Analytics</h1>
    </header>
    <div class="grid gap-2 lg:grid-cols-[minmax(0,1fr)_240px] lg:items-start">
      <div class="min-w-0 space-y-4">
        <div class="grid gap-2 lg:grid-cols-2 lg:items-stretch">
          <AnalyticsChartCard
            class="min-w-0 lg:h-[440px]"
            title="Competency Overview"
            skeleton-variant="vertical-bars"
            :meta="
              competencies.data.value
                ? `${competencies.data.value.pilotsWithCompletedTraining} pilots`
                : undefined
            "
            :is-loading="competencies.isLoading.value"
            :is-refreshing="competencies.isFetching.value"
            :error-message="competencies.isError.value ? error(competencies.error.value) : null"
            :has-content="competencyRows.length > 0"
            empty-message="No competency analytics are available for the selected filters."
            ><BarChart
              ariaLabel="Competency grade distribution chart"
              :data="competencyData"
              :options="verticalOptions"
              :height="304"
              :min-width="getGradeDistributionChartMinWidth(competencyRows.length)"
              fill-height
          /></AnalyticsChartCard>
          <AnalyticsChartCard
            class="min-w-0 lg:h-[440px]"
            title="Pilot Performance"
            skeleton-variant="horizontal-bars"
            :meta="
              pilotGrades.data.value
                ? countLabel(
                    filteredPilots.items.length,
                    pilotGrades.data.value.items.length,
                    'pilots',
                  )
                : undefined
            "
            :is-loading="pilotGrades.isLoading.value"
            :is-refreshing="pilotGrades.isFetching.value"
            :error-message="pilotGrades.isError.value ? error(pilotGrades.error.value) : null"
            :has-content="pilotRows.length > 0"
            empty-message="No pilot analytics are available for the selected filters."
            ><template #controls
              ><PilotPerformanceFilters
                v-model:top-performers-count="topCount"
                v-model:training-concern-count="concernCount"
                :max-pilot-count="pilotGrades.data.value?.items.length ?? 0" /></template
            ><BarChart
              ariaLabel="Pilot grade distribution chart"
              :data="pilotData"
              :options="horizontalOptions"
              :height="getHorizontalGradeDistributionChartHeight(pilotRows.length)"
              :separator-after-index="separator"
              fill-height
          /></AnalyticsChartCard>
        </div>
        <div class="grid gap-2 lg:grid-cols-2 lg:items-stretch">
          <AnalyticsChartCard
            class="min-w-0 lg:h-[580px]"
            title="Line chart"
            skeleton-variant="line"
            :meta="
              trend.data.value
                ? `${trend.data.value.pilotsWithCompletedTraining} pilots`
                : undefined
            "
            :is-loading="trend.isLoading.value"
            :is-refreshing="trend.isFetching.value"
            :error-message="trend.isError.value ? error(trend.error.value) : null"
            :has-content="(trendItem?.points.length ?? 0) > 0"
            empty-message="No competency trend is available for the selected filters."
            ><template #controls
              ><CompetencyTrendFilters
                v-model:competence-id="trendSelected"
                :competence-options="trendOptions" /></template
            ><LineChart
              ariaLabel="Competency half-year average trend chart"
              :data="trendData"
              :options="trendChartOptions"
              :min-width="getCompetencyAverageTrendChartMinWidth(trendItem?.points.length ?? 0)"
              fill-height
          /></AnalyticsChartCard>
          <AnalyticsChartCard
            class="min-w-0 lg:h-[580px]"
            title="Instructor Assessment"
            skeleton-variant="horizontal-bars"
            :meta="
              instructorGrades.data.value
                ? countLabel(
                    filteredInstructors.length,
                    instructorGrades.data.value.items.length,
                    'instructors',
                  )
                : undefined
            "
            :is-loading="instructorGrades.isLoading.value"
            :is-refreshing="instructorGrades.isFetching.value"
            :error-message="
              instructorGrades.isError.value ? error(instructorGrades.error.value) : null
            "
            :has-content="instructorRows.length > 0"
            empty-message="No instructor analytics are available for the selected filters."
            ><template #controls
              ><InstructorAssessmentFilters
                v-model:score-spread="instructorFilters.scoreSpread"
                v-model:variance-min="instructorFilters.varianceMin"
                v-model:variance-max="instructorFilters.varianceMax"
                v-model:lowest-grade-usage-min="instructorFilters.lowestGradeUsageMin"
                v-model:highest-grade-usage-min="instructorFilters.highestGradeUsageMin"
                v-model:extreme-grade-usage-min="
                  instructorFilters.extremeGradeUsageMin
                " /></template
            ><BarChart
              ariaLabel="Instructor grade distribution chart"
              :data="instructorData"
              :options="horizontalOptions"
              :height="getHorizontalGradeDistributionChartHeight(instructorRows.length)"
              fill-height
          /></AnalyticsChartCard>
        </div>
      </div>
      <aside class="relative z-30 order-first lg:sticky lg:top-0 lg:order-none">
        <div class="space-y-4">
          <AnalyticsFilters
            v-model:aircraft-id="aircraftId"
            v-model:position-id="positionId"
            v-model:age-from-years="ageFrom"
            v-model:age-to-years="ageTo"
            v-model:as-of-date="date"
            :pilot-search="pilotSearch"
            :aircraft-options="aircraftOptions"
            :pilot-options="pilotOptions"
            :position-options="positionOptions"
            :is-aircraft-loading="aircraft.isLoading.value"
            :is-pilot-loading="pilots.isLoading.value"
            :is-position-loading="positions.isLoading.value"
            @pilot-search-change="changePilot"
            @pilot-select="selectPilot"
            @pilot-clear="
              () => {
                selectedPilot = null
                pilotSearch = ''
              }
            "
            @reset="reset"
          />
          <section
            v-if="ageError"
            class="rounded-2xl border border-line-warning bg-warning-soft px-4 py-3 text-sm text-warning"
          >
            {{ ageError }}
          </section>
          <section
            v-if="lookupError"
            class="rounded-2xl border border-line-warning bg-warning-soft px-4 py-3 text-sm text-warning"
          >
            {{ lookupError }}
          </section>
        </div>
      </aside>
    </div>
  </section>
</template>
