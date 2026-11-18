<script setup lang="ts">
import AutocompleteSelect from '@/shared/ui/inputs/AutocompleteSelect.vue'
import type { AutocompleteOption } from '@/shared/ui/inputs/autocomplete'
defineProps<{
  completedFromValue: string
  completedToValue: string
  aircraftIdValue: number | null
  aircraftOptions: { id: number; label: string }[]
  scenarioValue: string
  scenarioOptions: AutocompleteOption[]
  instructorValue: string
  instructorOptions: AutocompleteOption[]
  participantValue: string
  participantOptions: AutocompleteOption[]
  isAircraftLoading?: boolean
  isScenarioLoading?: boolean
  isInstructorLoading?: boolean
  isParticipantLoading?: boolean
  limitValue: number
}>()
const emit = defineEmits<{
  completedFromChange: [value: string]
  completedToChange: [value: string]
  aircraftChange: [value: number | null]
  scenarioValueChange: [value: string]
  scenarioSelect: [option: AutocompleteOption]
  scenarioClear: []
  instructorValueChange: [value: string]
  instructorSelect: [option: AutocompleteOption]
  instructorClear: []
  participantValueChange: [value: string]
  participantSelect: [option: AutocompleteOption]
  participantClear: []
  limitChange: [value: number]
  reset: []
}>()
const fieldClass =
  'h-9 w-full rounded-xl border border-line bg-surface px-2.5 text-[13px] text-foreground outline-none transition focus:border-line-emphasis focus:ring-2 focus:ring-focus'
const dropdownClass = 'w-[min(28rem,calc(100vw-2rem))] min-w-full max-h-[24rem]'
function value(event: Event) {
  return (event.target as HTMLInputElement).value
}
</script>
<template>
  <section class="mx-auto w-full rounded-[28px] border border-line bg-surface p-3 shadow-sm lg:p-4">
    <div class="space-y-2 text-center">
      <div
        class="inline-flex rounded-full bg-surface-subtle px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.18em] text-foreground-inverse"
      >
        Filters
      </div>
    </div>
    <div class="mt-3 grid gap-2.5">
      <label class="flex w-full flex-col gap-1.5"
        ><span class="text-xs font-semibold uppercase tracking-wide text-foreground"
          >Completed from</span
        ><input
          type="date"
          :value="completedFromValue"
          :class="fieldClass"
          @change="emit('completedFromChange', value($event))"
      /></label>
      <label class="flex w-full flex-col gap-1.5"
        ><span class="text-xs font-semibold uppercase tracking-wide text-foreground"
          >Completed to</span
        ><input
          type="date"
          :value="completedToValue"
          :class="fieldClass"
          @change="emit('completedToChange', value($event))"
      /></label>
      <label class="flex w-full flex-col gap-1.5"
        ><span class="text-xs font-semibold uppercase tracking-wide text-foreground">Aircraft</span
        ><select
          :value="aircraftIdValue ?? ''"
          :class="fieldClass"
          :disabled="isAircraftLoading && aircraftOptions.length === 0"
          @change="emit('aircraftChange', value($event) ? Number(value($event)) : null)"
        >
          <option value="">All aircraft</option>
          <option v-for="aircraft in aircraftOptions" :key="aircraft.id" :value="aircraft.id">
            {{ aircraft.label }}
          </option>
        </select></label
      >
      <AutocompleteSelect
        label="Scenario"
        :value="scenarioValue"
        :options="scenarioOptions"
        placeholder="Search scenarios"
        empty-message="No scenarios found."
        :is-loading="isScenarioLoading"
        :dropdown-class-name="dropdownClass"
        @value-change="emit('scenarioValueChange', $event)"
        @option-select="emit('scenarioSelect', $event)"
        @clear="emit('scenarioClear')"
      />
      <AutocompleteSelect
        label="Instructor"
        :value="instructorValue"
        :options="instructorOptions"
        placeholder="Search instructors"
        empty-message="No instructors found."
        :is-loading="isInstructorLoading"
        :dropdown-class-name="dropdownClass"
        @value-change="emit('instructorValueChange', $event)"
        @option-select="emit('instructorSelect', $event)"
        @clear="emit('instructorClear')"
      />
      <AutocompleteSelect
        label="Participant"
        :value="participantValue"
        :options="participantOptions"
        placeholder="Search either participant"
        empty-message="No participant matches found."
        :is-loading="isParticipantLoading"
        :dropdown-class-name="dropdownClass"
        @value-change="emit('participantValueChange', $event)"
        @option-select="emit('participantSelect', $event)"
        @clear="emit('participantClear')"
      />
      <label class="flex w-full flex-col gap-1.5"
        ><span class="text-xs font-semibold uppercase tracking-wide text-foreground">Page size</span
        ><select
          :value="limitValue"
          :class="fieldClass"
          @change="emit('limitChange', Number(value($event)))"
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
