<script setup lang="ts">
import AutocompleteSelect from '@/shared/ui/inputs/AutocompleteSelect.vue'
import type { AutocompleteOption } from '@/shared/ui/inputs/autocomplete'
const aircraftId = defineModel<number | null>('aircraftId', { required: true })
const positionId = defineModel<number | null>('positionId', { required: true })
const ageFrom = defineModel<number | null>('ageFromYears', { required: true })
const ageTo = defineModel<number | null>('ageToYears', { required: true })
const date = defineModel<string>('asOfDate', { required: true })
defineProps<{
  pilotSearch: string
  aircraftOptions: { id: number; label: string }[]
  positionOptions: { id: number; label: string }[]
  pilotOptions: AutocompleteOption[]
  isAircraftLoading?: boolean
  isPilotLoading?: boolean
  isPositionLoading?: boolean
}>()
const emit = defineEmits<{
  pilotSearchChange: [value: string]
  pilotSelect: [option: AutocompleteOption]
  pilotClear: []
  reset: []
}>()
const fieldClass =
  'h-9 w-full min-w-0 max-w-full rounded-xl border border-line bg-surface px-2.5 text-[13px] text-foreground outline-none transition focus:border-line-emphasis focus:ring-2 focus:ring-focus'
function number(event: Event) {
  const value = (event.target as HTMLInputElement).value
  return value ? Number(value) : null
}
</script>
<template>
  <section class="w-full min-w-0 rounded-[28px] border border-line bg-surface p-4 shadow-sm lg:p-5">
    <header class="mb-3 flex flex-col gap-2.5 md:flex-row md:items-start md:justify-between">
      <div class="space-y-1">
        <h2 class="text-lg font-semibold tracking-tight text-foreground">Filters</h2>
      </div>
    </header>
    <div class="grid gap-2.5">
      <label class="flex w-full min-w-0 flex-col gap-1.5"
        ><span class="text-xs font-semibold uppercase tracking-wide text-foreground">Aircraft</span
        ><select
          v-model="aircraftId"
          :class="fieldClass"
          :disabled="isAircraftLoading && !aircraftOptions.length"
        >
          <option :value="null">All aircraft</option>
          <option v-for="option in aircraftOptions" :key="option.id" :value="option.id">
            {{ option.label }}
          </option>
        </select></label
      >
      <label class="flex w-full min-w-0 flex-col gap-1.5"
        ><span class="text-xs font-semibold uppercase tracking-wide text-foreground">Position</span
        ><select
          v-model="positionId"
          :class="fieldClass"
          :disabled="isPositionLoading && !positionOptions.length"
        >
          <option :value="null">All positions</option>
          <option v-for="option in positionOptions" :key="option.id" :value="option.id">
            {{ option.label }}
          </option>
        </select></label
      >
      <AutocompleteSelect
        label="Pilot"
        :value="pilotSearch"
        :options="pilotOptions"
        placeholder="Search by first or last name"
        empty-message="No pilots found."
        :is-loading="isPilotLoading"
        :input-class-name="fieldClass"
        dropdown-class-name="w-[min(28rem,calc(100vw-2rem))] min-w-full"
        @value-change="emit('pilotSearchChange', $event)"
        @option-select="emit('pilotSelect', $event)"
        @clear="emit('pilotClear')"
      />
      <label class="flex w-full min-w-0 flex-col gap-1.5"
        ><span class="text-xs font-semibold uppercase tracking-wide text-foreground">Age from</span
        ><input
          type="number"
          inputmode="numeric"
          min="0"
          step="1"
          :value="ageFrom ?? ''"
          placeholder="Min age"
          :class="fieldClass"
          @input="ageFrom = number($event)"
      /></label>
      <label class="flex w-full min-w-0 flex-col gap-1.5"
        ><span class="text-xs font-semibold uppercase tracking-wide text-foreground">Age to</span
        ><input
          type="number"
          inputmode="numeric"
          min="0"
          step="1"
          :value="ageTo ?? ''"
          placeholder="Max age"
          :class="fieldClass"
          @input="ageTo = number($event)"
      /></label>
      <label class="flex w-full min-w-0 flex-col gap-1.5"
        ><span class="text-xs font-semibold uppercase tracking-wide text-foreground"
          >As of date</span
        ><input v-model="date" type="date" :class="fieldClass"
      /></label>
      <div class="flex w-full min-w-0 flex-col gap-1.5">
        <button
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
