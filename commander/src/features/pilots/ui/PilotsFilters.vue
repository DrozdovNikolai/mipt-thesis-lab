<script setup lang="ts">
import { computed } from 'vue'
import type { PilotSortOption } from '@/entities/commander/types'

export type ActivityFilter = 'all' | 'active' | 'inactive'
const props = withDefaults(
  defineProps<{
    searchValue: string
    sortValue: PilotSortOption
    activityValue: ActivityFilter
    aircraftIdValue: number | null
    layout?: 'toolbar' | 'sidebar'
    aircraftOptions: { id: number; label: string }[]
    isAircraftLoading?: boolean
    limitValue: number
  }>(),
  { layout: 'toolbar', isAircraftLoading: false },
)
const emit = defineEmits<{
  searchChange: [value: string]
  sortChange: [value: PilotSortOption]
  activityChange: [value: ActivityFilter]
  aircraftChange: [value: number | null]
  limitChange: [value: number]
  reset: []
}>()
const sortChoices: { value: PilotSortOption; label: string }[] = [
  { value: 'createdAtDesc', label: 'Newest first' },
  { value: 'createdAtAsc', label: 'Oldest first' },
  { value: 'loginAsc', label: 'Login A-Z' },
  { value: 'loginDesc', label: 'Login Z-A' },
  { value: 'emailAsc', label: 'Email A-Z' },
  { value: 'emailDesc', label: 'Email Z-A' },
  { value: 'lastNameAsc', label: 'Last name A-Z' },
  { value: 'lastNameDesc', label: 'Last name Z-A' },
]
const fieldClass = computed(
  () =>
    'w-full rounded-xl border border-line bg-surface text-foreground outline-none transition focus:border-line-emphasis focus:ring-2 focus:ring-focus ' +
    (props.layout === 'sidebar' ? 'h-9 px-2.5 text-[13px]' : 'h-10 px-3 text-sm'),
)
const valueOf = (event: Event) => (event.target as HTMLInputElement | HTMLSelectElement).value
</script>
<template>
  <section
    :class="
      layout === 'sidebar'
        ? 'mx-auto w-full rounded-[28px] border border-line bg-surface p-3 shadow-sm lg:p-4'
        : 'rounded-2xl border border-line bg-surface p-4 shadow-sm'
    "
  >
    <div v-if="layout === 'sidebar'" class="space-y-2 text-center">
      <div
        class="inline-flex rounded-full bg-surface-subtle px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.18em] text-foreground-inverse"
      >
        Filters
      </div>
    </div>
    <div
      :class="
        layout === 'sidebar' ? 'mt-3 grid gap-2.5' : 'grid gap-3 md:grid-cols-2 xl:grid-cols-6'
      "
    >
      <label class="flex w-full flex-col gap-1.5"
        ><span class="text-xs font-semibold uppercase tracking-wide text-foreground">Search</span
        ><input
          :value="searchValue"
          placeholder="Search by login, email, name"
          :class="fieldClass"
          @input="emit('searchChange', valueOf($event))"
      /></label>
      <label class="flex w-full flex-col gap-1.5"
        ><span class="text-xs font-semibold uppercase tracking-wide text-foreground">Status</span
        ><select
          :value="activityValue"
          :class="fieldClass"
          @change="emit('activityChange', valueOf($event) as ActivityFilter)"
        >
          <option value="all">All</option>
          <option value="active">Active</option>
          <option value="inactive">Inactive</option>
        </select></label
      >
      <label class="flex w-full flex-col gap-1.5"
        ><span class="text-xs font-semibold uppercase tracking-wide text-foreground">Sort</span
        ><select
          :value="sortValue"
          :class="fieldClass"
          @change="emit('sortChange', valueOf($event) as PilotSortOption)"
        >
          <option v-for="choice in sortChoices" :key="choice.value" :value="choice.value">
            {{ choice.label }}
          </option>
        </select></label
      >
      <label class="flex w-full flex-col gap-1.5"
        ><span class="text-xs font-semibold uppercase tracking-wide text-foreground">Aircraft</span
        ><select
          :value="aircraftIdValue ?? ''"
          :class="fieldClass"
          :disabled="isAircraftLoading && aircraftOptions.length === 0"
          @change="emit('aircraftChange', valueOf($event) ? Number(valueOf($event)) : null)"
        >
          <option value="">All aircraft</option>
          <option v-for="option in aircraftOptions" :key="option.id" :value="option.id">
            {{ option.label }}
          </option>
        </select></label
      >
      <label class="flex w-full flex-col gap-1.5"
        ><span class="text-xs font-semibold uppercase tracking-wide text-foreground">Page size</span
        ><select
          :value="limitValue"
          :class="fieldClass"
          @change="emit('limitChange', Number(valueOf($event)))"
        >
          <option v-for="limit in [20, 50, 100]" :key="limit" :value="limit">{{ limit }}</option>
        </select></label
      >
      <div class="flex w-full flex-col gap-1.5">
        <span class="text-xs font-semibold uppercase tracking-wide text-foreground">Filters</span
        ><button
          type="button"
          class="inline-flex h-9 w-full items-center justify-center rounded-xl border border-line-strong bg-surface-muted px-3 text-[13px] font-medium text-foreground-secondary transition hover:border-line-emphasis hover:bg-surface-subtle hover:text-foreground-inverse"
          @click="emit('reset')"
        >
          Reset filters
        </button>
      </div>
    </div>
  </section>
</template>
