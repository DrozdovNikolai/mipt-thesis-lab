<script setup lang="ts">
import { computed, ref, shallowRef, useId, watch } from 'vue'
import { keepPreviousData, useQuery } from '@tanstack/vue-query'
import { commanderApi } from '@/entities/commander/api'
import { commanderKeys } from '@/entities/commander/queryKeys'
import type { SessionUser } from '@/entities/session/types'
import { useSessionStore } from '@/entities/session/store'
import { useSessionScope } from '@/entities/session/useSessionScope'
import { getErrorMessage } from '@/shared/lib/errorMessage'
import { useDebouncedValue } from '@/shared/lib/useDebouncedValue'
import AutocompleteSelect from '@/shared/ui/inputs/AutocompleteSelect.vue'
import type { AutocompleteOption } from '@/shared/ui/inputs/autocomplete'
const trainingTypeLabelId = useId(),
  trainingTypeHelpId = useId()
const props = defineProps<{ asOfDate: string }>()
const session = useSessionStore(),
  scope = useSessionScope()
const firstInput = ref(''),
  secondInput = ref(''),
  first = shallowRef<SessionUser | null>(null),
  second = shallowRef<SessionUser | null>(null),
  typeId = ref<number | null>(null)
const firstSearch = useDebouncedValue(firstInput, 250),
  secondSearch = useDebouncedValue(secondInput, 250)
function searchPilots(search: Readonly<{ value: string }>) {
  return useQuery({
    queryKey: computed(() => [
      ...commanderKeys.root(scope.value),
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
}
const firstQuery = searchPilots(firstSearch),
  secondQuery = searchPilots(secondSearch)
const types = useQuery({
  queryKey: computed(() => commanderKeys.flightTypes(scope.value)),
  queryFn: () => commanderApi.listFlightTypes(),
  enabled: computed(() => session.isReady),
  retry: 0,
})
watch(types.data, (values) => {
  if (typeId.value !== null && values && !values.some((value) => value.id === typeId.value)) {
    typeId.value = null
  }
})
const same = computed(() =>
  Boolean(first.value && second.value && first.value.id === second.value.id),
)
const canCompare = computed(() =>
  Boolean(session.isReady && first.value && second.value && typeId.value && !same.value),
)
const query = useQuery({
  queryKey: computed(() => [
    ...commanderKeys.compatibility(scope.value),
    first.value?.id ?? null,
    second.value?.id ?? null,
    typeId.value,
    props.asOfDate,
  ]),
  queryFn: ({ signal }) => {
    if (!first.value || !second.value || !typeId.value || same.value)
      throw new Error('Select two different pilots and a training type.')
    return commanderApi.getPilotCompatibility(
      {
        firstPilotId: first.value.id,
        secondPilotId: second.value.id,
        flightTypeId: typeId.value,
        asOfDate: props.asOfDate || undefined,
      },
      signal,
    )
  },
  enabled: canCompare,
  placeholderData: keepPreviousData,
  retry: 0,
})
const personName = (pilot: SessionUser) =>
  [pilot.firstName?.trim(), pilot.lastName?.trim()].filter(Boolean).join(' ').trim() ||
  pilot.login ||
  pilot.email
const options = (users: SessionUser[]) =>
  users.map((pilot) => ({
    value: pilot.id,
    label: personName(pilot),
    description: pilot.email,
    meta: pilot.position,
    pilot,
  }))
const firstOptions = computed(() =>
  options(firstQuery.data.value?.items ?? []).filter((item) => item.value !== second.value?.id),
)
const secondOptions = computed(() =>
  options(secondQuery.data.value?.items ?? []).filter((item) => item.value !== first.value?.id),
)
const data = computed(() => (canCompare.value ? query.data.value : undefined))
const summary = computed(() => {
  const items = data.value?.items ?? []
  const configured = items.filter((item) => item.thresholdConfigured),
    compatible = configured.filter((item) => item.compatible)
  const incompatible = configured.filter((item) => !item.compatible)
  return {
    label: !configured.length
      ? 'Thresholds not configured'
      : !incompatible.length
        ? 'Compatible'
        : 'Not compatible',
    tone: !configured.length ? 'warning' : !incompatible.length ? 'success' : 'danger',
    configuredCount: configured.length,
    compatibleCount: compatible.length,
    incompatibleCount: incompatible.length,
    unconfiguredCount: items.length - configured.length,
  }
})
const error = (value: unknown) => getErrorMessage(value, 'Failed to load compatibility.')
const warnings = computed(() =>
  [
    types.isError.value ? error(types.error.value) : null,
    firstQuery.isError.value ? error(firstQuery.error.value) : null,
    secondQuery.isError.value ? error(secondQuery.error.value) : null,
  ].filter((value): value is string => Boolean(value)),
)
const pilotLabel = (
  pilot: { firstName: string | null; lastName: string | null },
  fallback: string,
) => [pilot.firstName?.trim(), pilot.lastName?.trim()].filter(Boolean).join(' ').trim() || fallback
function numeric(value: string | number | null, fallback: string) {
  if (value === null) return fallback
  const n = Number(value)
  return Number.isFinite(n) ? n.toFixed(2).replace(/\.?0+$/, '') || '0' : String(value)
}
const toneClass = (tone: string) =>
  tone === 'success'
    ? 'rounded-2xl border border-line-success bg-success-soft p-4'
    : tone === 'danger'
      ? 'rounded-2xl border border-line-danger bg-danger-soft p-4'
      : 'rounded-2xl border border-line-warning bg-warning-soft p-4'
function change(which: 1 | 2, value: string) {
  const input = which === 1 ? firstInput : secondInput,
    pilot = which === 1 ? first : second
  input.value = value
  if (pilot.value && value !== personName(pilot.value)) pilot.value = null
}
function select(which: 1 | 2, option: AutocompleteOption) {
  const found = (which === 1 ? firstOptions : secondOptions).value.find(
    (item) => item.value === option.value,
  )
  if (!found) return
  if (which === 1) {
    first.value = found.pilot
    firstInput.value = found.label
  } else {
    second.value = found.pilot
    secondInput.value = found.label
  }
}
function reset() {
  firstInput.value = ''
  secondInput.value = ''
  first.value = null
  second.value = null
  typeId.value = null
}
</script>
<template>
  <section class="rounded-[28px] border border-line bg-surface p-5 shadow-sm">
    <header class="mb-4 flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
      <div class="space-y-1">
        <h2 class="text-lg font-semibold tracking-tight text-foreground">Pilot pairing analysis</h2>
        <p class="max-w-3xl text-sm text-foreground">
          Compare CM 1 and CM 2 against a selected training type and review where the pair is
          compatible or incompatible. The selected As of date is applied when it is set.
        </p>
      </div>
      <span
        class="inline-flex h-8 items-center rounded-full bg-surface-subtle px-3 text-xs font-semibold text-foreground-inverse"
        >{{ asOfDate ? `As of ${asOfDate}` : 'Latest completed training' }}</span
      >
    </header>
    <div class="grid gap-3 xl:grid-cols-[1.2fr_1.2fr_1fr_auto]">
      <AutocompleteSelect
        label="CM 1"
        :value="firstInput"
        :options="firstOptions"
        placeholder="Search pilot by name, login, or email"
        helper-text="Select the first crew member."
        :is-loading="firstQuery.isLoading.value"
        @value-change="change(1, $event)"
        @option-select="select(1, $event)"
        @clear="
          () => {
            first = null
            firstInput = ''
          }
        "
      /><AutocompleteSelect
        label="CM 2"
        :value="secondInput"
        :options="secondOptions"
        placeholder="Search pilot by name, login, or email"
        helper-text="Select the second crew member."
        :is-loading="secondQuery.isLoading.value"
        @value-change="change(2, $event)"
        @option-select="select(2, $event)"
        @clear="
          () => {
            second = null
            secondInput = ''
          }
        "
      /><label class="flex flex-col gap-1.5"
        ><span
          :id="trainingTypeLabelId"
          class="text-xs font-semibold uppercase tracking-wide text-foreground"
          >Training type</span
        ><select
          v-model="typeId"
          :aria-labelledby="trainingTypeLabelId"
          :aria-describedby="trainingTypeHelpId"
          :disabled="types.isLoading.value"
          class="h-10 rounded-xl border border-line bg-surface px-3 text-sm text-foreground outline-none transition focus:border-line-emphasis focus:ring-2 focus:ring-focus"
        >
          <option :value="null">Select type</option>
          <option v-for="type in types.data.value ?? []" :key="type.id" :value="type.id">
            {{ type.name }}
          </option></select
        ><span :id="trainingTypeHelpId" class="text-xs text-foreground"
          >Flight type thresholds define compatibility rules.</span
        ></label
      >
      <div class="flex flex-col gap-1.5">
        <span class="text-xs font-semibold uppercase tracking-wide text-foreground">Selection</span
        ><button
          type="button"
          class="inline-flex h-10 items-center justify-center rounded-xl border border-line-strong bg-surface-muted px-4 text-sm font-medium text-foreground-secondary transition hover:border-line-emphasis hover:bg-surface-subtle hover:text-foreground-inverse"
          @click="reset"
        >
          Reset
        </button>
      </div>
    </div>
    <div
      v-for="warning in warnings"
      :key="warning"
      class="mt-4 rounded-2xl border border-line-warning bg-warning-soft px-4 py-3 text-sm text-warning"
    >
      {{ warning }}
    </div>
    <div
      v-if="same"
      class="mt-4 rounded-2xl border border-line-warning bg-warning-soft px-4 py-3 text-sm text-warning"
    >
      CM 1 and CM 2 must be different pilots.
    </div>
    <div
      v-if="!first || !second || !typeId"
      class="mt-4 rounded-2xl border border-dashed border-line-strong bg-surface-muted px-5 py-10 text-center text-sm text-foreground"
    >
      Select CM 1, CM 2, and a training type to evaluate pilot compatibility.
    </div>
    <div v-if="canCompare && query.isLoading.value && !data" class="mt-4 space-y-3">
      <div
        v-for="index in 3"
        :key="index"
        class="h-24 animate-pulse rounded-2xl bg-surface-subtle"
        aria-hidden="true"
      />
    </div>
    <div
      v-if="canCompare && query.isError.value && !data"
      role="alert"
      class="mt-4 rounded-2xl border border-line-danger bg-danger-soft px-4 py-3 text-sm text-danger"
    >
      {{ error(query.error.value) }}
    </div>
    <div v-if="data" class="mt-4 space-y-4">
      <div
        v-if="query.isError.value"
        class="rounded-2xl border border-line-warning bg-warning-soft px-4 py-3 text-sm text-warning"
      >
        {{ error(query.error.value) }}
      </div>
      <p v-if="query.isFetching.value" role="status" class="text-sm text-foreground-secondary">
        Updating comparison...
      </p>
      <div class="grid gap-3 lg:grid-cols-[1.2fr_1fr_1fr_1fr]">
        <article :class="toneClass(summary.tone)">
          <p class="text-xs font-semibold uppercase tracking-[0.14em] text-foreground-secondary">
            Overall status
          </p>
          <p class="mt-2 text-2xl font-semibold tracking-tight text-foreground">
            {{ summary.label }}
          </p>
          <p class="mt-2 text-sm text-foreground-secondary">
            Flight type: {{ data.flightType.name }}
          </p>
        </article>
        <article
          v-for="(pilot, index) in [data.firstPilot, data.secondPilot]"
          :key="index"
          class="rounded-2xl border border-line bg-surface-muted p-4"
        >
          <p class="text-xs font-semibold uppercase tracking-[0.14em] text-foreground">
            CM {{ index + 1 }}
          </p>
          <p class="mt-2 text-lg font-semibold text-foreground">
            {{ pilotLabel(pilot, `CM ${index + 1}`) }}
          </p>
          <p class="mt-2 text-sm text-foreground">
            {{ pilot.hasCompletedTraining ? 'Completed training found' : 'No completed training' }}
          </p>
        </article>
        <article class="rounded-2xl border border-line bg-surface-muted p-4">
          <p class="text-xs font-semibold uppercase tracking-[0.14em] text-foreground">Coverage</p>
          <p class="mt-2 text-lg font-semibold text-foreground">
            {{ summary.compatibleCount }}/{{ summary.configuredCount }} compatible
          </p>
          <p class="mt-2 text-sm text-foreground">
            {{ summary.incompatibleCount }} incompatible, {{ summary.unconfiguredCount }} not
            configured
          </p>
        </article>
      </div>
      <div class="space-y-3">
        <article
          v-for="item in data.items"
          :key="item.competenceId"
          :class="
            toneClass(
              !item.thresholdConfigured ? 'warning' : item.compatible ? 'success' : 'danger',
            )
          "
        >
          <div class="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
            <div>
              <div class="flex items-center gap-2">
                <span
                  class="inline-flex rounded-full bg-surface px-2 py-1 text-[11px] font-semibold uppercase tracking-wide text-foreground"
                  >{{ item.competenceCode }}</span
                ><span
                  :class="[
                    'inline-flex rounded-full px-2 py-1 text-[11px] font-semibold uppercase tracking-wide',
                    !item.thresholdConfigured
                      ? 'bg-warning-muted text-warning'
                      : item.compatible
                        ? 'bg-success-muted text-success'
                        : 'bg-danger-muted text-danger',
                  ]"
                  >{{
                    !item.thresholdConfigured
                      ? 'No threshold'
                      : item.compatible
                        ? 'Compatible'
                        : 'Incompatible'
                  }}</span
                >
              </div>
              <h3 class="mt-2 text-base font-semibold text-foreground">
                {{ item.competenceName }}
              </h3>
            </div>
            <div class="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
              <div
                v-for="field in [
                  { label: 'CM 1', value: item.firstPilotValue, fallback: 'No grade' },
                  { label: 'CM 2', value: item.secondPilotValue, fallback: 'No grade' },
                  { label: 'Actual sum', value: item.actualSum, fallback: 'Missing data' },
                  { label: 'Required sum', value: item.requiredSum, fallback: 'Not configured' },
                ]"
                :key="field.label"
              >
                <p class="text-xs font-semibold uppercase tracking-wide text-foreground">
                  {{ field.label }}
                </p>
                <p class="mt-1 text-sm font-medium text-foreground">
                  {{ numeric(field.value, field.fallback) }}
                </p>
              </div>
            </div>
          </div>
        </article>
      </div>
    </div>
  </section>
</template>
