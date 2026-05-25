<script setup lang="ts">
import { computed, ref } from 'vue'
import { keepPreviousData, useQuery } from '@tanstack/vue-query'
import { commanderApi } from '@/entities/commander/api'
import { commanderKeys } from '@/entities/commander/queryKeys'
import type { PilotSortOption } from '@/entities/commander/types'
import { useSessionStore } from '@/entities/session/store'
import { useSessionScope } from '@/entities/session/useSessionScope'
import { useDebouncedValue } from '@/shared/lib/useDebouncedValue'
import { getErrorMessage } from '@/shared/lib/errorMessage'
import PilotsFilters from '@/features/pilots/ui/PilotsFilters.vue'
import type { ActivityFilter } from '@/features/pilots/ui/PilotsFilters.vue'
import PilotsList from '@/features/pilots/ui/PilotsList.vue'
import ResultsPagination from '@/shared/ui/lists/ResultsPagination.vue'

const session = useSessionStore()
const scope = useSessionScope()
const search = ref('')
const sort = ref<PilotSortOption>('lastNameAsc')
const activity = ref<ActivityFilter>('all')
const aircraftId = ref<number | null>(null)
const limit = ref(20)
const offset = ref(0)
const debouncedSearch = useDebouncedValue(search, 350)
const {
  data: aircraft,
  isLoading: aircraftLoading,
  error: aircraftError,
} = useQuery({
  queryKey: computed(() => commanderKeys.aircraft(scope.value)),
  queryFn: ({ signal }) => commanderApi.listAircraft(signal),
  enabled: computed(() => session.isReady),
  retry: 0,
})
const filters = computed(() => ({
  q: debouncedSearch.value.trim() || undefined,
  sort: sort.value,
  isActive: activity.value === 'all' ? undefined : activity.value === 'active',
  aircraftId: aircraftId.value ?? undefined,
  limit: limit.value,
  offset: offset.value,
}))
const {
  data: pilots,
  isLoading,
  error,
} = useQuery({
  queryKey: computed(() => commanderKeys.pilots(scope.value, filters.value)),
  queryFn: ({ signal }) => commanderApi.listPilots(filters.value, signal),
  enabled: computed(() => session.isReady),
  placeholderData: keepPreviousData,
})
const aircraftOptions = computed(() =>
  (aircraft.value ?? []).map((item) => ({ id: item.id, label: item.code })),
)
const aircraftColors = computed(() =>
  Object.fromEntries((aircraft.value ?? []).map((item) => [item.code, item.colorHex])),
)
const total = computed(() => pilots.value?.total ?? 0)
function changeSearch(value: string) {
  search.value = value
  offset.value = 0
}
function changeSort(value: PilotSortOption) {
  sort.value = value
  offset.value = 0
}
function changeActivity(value: ActivityFilter) {
  activity.value = value
  offset.value = 0
}
function changeAircraft(value: number | null) {
  aircraftId.value = value
  offset.value = 0
}
function changeLimit(value: number) {
  limit.value = value
  offset.value = 0
}
function reset() {
  search.value = ''
  sort.value = 'lastNameAsc'
  activity.value = 'all'
  aircraftId.value = null
  limit.value = 20
  offset.value = 0
}
</script>
<template>
  <section class="flex flex-col gap-4">
    <div class="space-y-4 lg:mx-auto lg:w-max lg:max-w-full">
      <header class="space-y-1">
        <h1 class="text-2xl font-semibold tracking-tight text-foreground">Pilots</h1>
      </header>
      <div class="grid gap-4 lg:grid-cols-[auto_240px] lg:items-start lg:gap-3 2xl:gap-4">
        <div class="min-w-0 space-y-4">
          <section
            v-if="error"
            role="alert"
            class="rounded-2xl border border-line-danger bg-danger-soft px-4 py-3 text-sm text-danger"
          >
            {{ getErrorMessage(error, 'Failed to load pilots list.') }}
          </section>
          <div class="w-max max-w-full space-y-4">
            <PilotsList
              :pilots="pilots?.items ?? []"
              :aircraft-colors-by-code="aircraftColors"
              :is-loading="isLoading"
            />
            <ResultsPagination
              :total="total"
              :limit="limit"
              :offset="offset"
              @previous="offset = Math.max(0, offset - limit)"
              @next="offset + limit < total && (offset += limit)"
            />
          </div>
        </div>
        <aside class="lg:self-start lg:sticky lg:top-0">
          <div class="space-y-4">
            <PilotsFilters
              :search-value="search"
              :sort-value="sort"
              :activity-value="activity"
              :aircraft-id-value="aircraftId"
              layout="sidebar"
              :aircraft-options="aircraftOptions"
              :is-aircraft-loading="aircraftLoading"
              :limit-value="limit"
              @search-change="changeSearch"
              @sort-change="changeSort"
              @activity-change="changeActivity"
              @aircraft-change="changeAircraft"
              @limit-change="changeLimit"
              @reset="reset"
            />
            <section
              v-if="aircraftError"
              role="alert"
              class="rounded-2xl border border-line-warning bg-warning-soft px-4 py-3 text-sm text-warning"
            >
              {{ getErrorMessage(aircraftError, 'Failed to load aircraft lookup.') }}
            </section>
          </div>
        </aside>
      </div>
    </div>
  </section>
</template>
