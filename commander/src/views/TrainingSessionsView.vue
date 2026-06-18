<script setup lang="ts">
import { computed, ref, shallowRef } from 'vue'
import { keepPreviousData, useQuery } from '@tanstack/vue-query'
import { commanderApi } from '@/entities/commander/api'
import { commanderKeys } from '@/entities/commander/queryKeys'
import type { CommanderScenarioLookupItem } from '@/entities/commander/types'
import type { SessionUser } from '@/entities/session/types'
import { useSessionStore } from '@/entities/session/store'
import { useSessionScope } from '@/entities/session/useSessionScope'
import TrainingSessionsFilters from '@/features/training-sessions/ui/TrainingSessionsFilters.vue'
import TrainingSessionsList from '@/features/training-sessions/ui/TrainingSessionsList.vue'
import { getErrorMessage as errorMessage } from '@/shared/lib/errorMessage'
import { useDebouncedValue } from '@/shared/lib/useDebouncedValue'
import type { AutocompleteOption } from '@/shared/ui/inputs/autocomplete'
import ResultsPagination from '@/shared/ui/lists/ResultsPagination.vue'
const session = useSessionStore()
const scope = useSessionScope()
const completedFrom = ref(''),
  completedTo = ref(''),
  aircraftId = ref<number | null>(null)
const scenarioInput = ref(''),
  instructorInput = ref(''),
  participantInput = ref('')
const selectedScenario = shallowRef<CommanderScenarioLookupItem | null>(null)
const selectedInstructor = shallowRef<SessionUser | null>(null),
  selectedParticipant = shallowRef<SessionUser | null>(null)
const limit = ref(20),
  offset = ref(0)
const debouncedScenario = useDebouncedValue(scenarioInput, 250)
const debouncedInstructor = useDebouncedValue(instructorInput, 250)
const debouncedParticipant = useDebouncedValue(participantInput, 250)
const dateError = computed(() =>
  completedFrom.value && completedTo.value && completedFrom.value > completedTo.value
    ? 'Completed from date must be before or equal to completed to date.'
    : null,
)
const aircraftQuery = useQuery({
  queryKey: computed(() => commanderKeys.aircraft(scope.value)),
  queryFn: ({ signal }) => commanderApi.listAircraft(signal),
  enabled: computed(() => session.isReady),
  retry: 0,
})
const scenariosQuery = useQuery({
  queryKey: computed(() => [
    ...commanderKeys.root(scope.value),
    'scenario-lookup',
    debouncedScenario.value.trim().toLowerCase(),
    aircraftId.value,
  ]),
  queryFn: ({ signal }) =>
    commanderApi.listScenarios(
      {
        q: debouncedScenario.value.trim() || undefined,
        aircraftId: aircraftId.value ?? undefined,
        limit: 10,
      },
      signal,
    ),
  enabled: computed(() => session.isReady),
  placeholderData: keepPreviousData,
  retry: 0,
})
function userLookup(key: string, search: Readonly<{ value: string }>) {
  return useQuery({
    queryKey: computed(() => [
      ...commanderKeys.root(scope.value),
      key,
      search.value.trim().toLowerCase(),
      aircraftId.value,
    ]),
    queryFn: ({ signal }) =>
      commanderApi.listPilots(
        {
          q: search.value.trim() || undefined,
          aircraftId: aircraftId.value ?? undefined,
          sort: 'lastNameAsc',
          limit: 10,
        },
        signal,
      ),
    enabled: computed(() => session.isReady),
    placeholderData: keepPreviousData,
    retry: 0,
  })
}
const instructors = userLookup('training-sessions-instructor-lookup', debouncedInstructor)
const participants = userLookup('training-sessions-participant-lookup', debouncedParticipant)
const filters = computed(() => ({
  completedFrom: completedFrom.value || undefined,
  completedTo: completedTo.value || undefined,
  scenarioId: selectedScenario.value?.id,
  instructorId: selectedInstructor.value?.id,
  participantId: selectedParticipant.value?.id,
  aircraftId: aircraftId.value ?? undefined,
  limit: limit.value,
  offset: offset.value,
}))
const sessionsQuery = useQuery({
  queryKey: computed(() => [
    ...commanderKeys.root(scope.value),
    'training-sessions',
    filters.value,
  ]),
  queryFn: ({ signal }) => commanderApi.listTrainingSessions(filters.value, signal),
  enabled: computed(() => session.isReady && !dateError.value),
  placeholderData: keepPreviousData,
  retry: 0,
})
const aircraftOptions = computed(() =>
  (aircraftQuery.data.value ?? []).map((aircraft) => ({ id: aircraft.id, label: aircraft.code })),
)
const aircraftLabels = computed(() =>
  Object.fromEntries(
    (aircraftQuery.data.value ?? []).map((aircraft) => [aircraft.id, aircraft.code]),
  ),
)
const aircraftColors = computed(() =>
  Object.fromEntries(
    (aircraftQuery.data.value ?? []).map((aircraft) => [aircraft.id, aircraft.colorHex]),
  ),
)
function personName(user: SessionUser) {
  return (
    [user.firstName?.trim(), user.lastName?.trim()].filter(Boolean).join(' ').trim() ||
    user.login ||
    user.email
  )
}
function scenarioName(scenario: CommanderScenarioLookupItem) {
  return scenario.aircraftCode ? `${scenario.title} (${scenario.aircraftCode})` : scenario.title
}
function peopleOptions(users: SessionUser[]) {
  return users.map((user) => ({
    value: user.id,
    label: personName(user),
    description: user.email,
    meta: user.position ?? user.aircraftCodes[0],
    user,
  }))
}
const scenarioOptions = computed(() =>
  (scenariosQuery.data.value?.items ?? []).map((scenario) => ({
    value: String(scenario.id),
    label: scenarioName(scenario),
    description: scenario.status,
    meta: scenario.aircraftCode,
    scenario,
  })),
)
const instructorOptions = computed(() => peopleOptions(instructors.data.value?.items ?? []))
const participantOptions = computed(() => peopleOptions(participants.data.value?.items ?? []))
const total = computed(() => sessionsQuery.data.value?.total ?? 0)
const lookupErrors = computed(() => [
  ...new Set(
    [
      aircraftQuery.isError.value
        ? errorMessage(aircraftQuery.error.value, 'Failed to load aircraft lookup.')
        : null,
      scenariosQuery.isError.value
        ? errorMessage(scenariosQuery.error.value, 'Failed to load scenarios lookup.')
        : null,
      instructors.isError.value
        ? errorMessage(instructors.error.value, 'Failed to load instructor lookup.')
        : null,
      participants.isError.value
        ? errorMessage(participants.error.value, 'Failed to load participant lookup.')
        : null,
    ].filter((message): message is string => Boolean(message)),
  ),
])
function changeAircraft(value: number | null) {
  aircraftId.value = value
  offset.value = 0
  if (selectedScenario.value && value !== null && selectedScenario.value.aircraftId !== value) {
    selectedScenario.value = null
    scenarioInput.value = ''
  }
}
function changeScenario(value: string) {
  scenarioInput.value = value
  offset.value = 0
  if (selectedScenario.value && value !== scenarioName(selectedScenario.value))
    selectedScenario.value = null
}
function changePerson(kind: 'instructor' | 'participant', value: string) {
  const input = kind === 'instructor' ? instructorInput : participantInput
  const selected = kind === 'instructor' ? selectedInstructor : selectedParticipant
  input.value = value
  offset.value = 0
  if (selected.value && value !== personName(selected.value)) selected.value = null
}
function selectScenario(option: AutocompleteOption) {
  const match = scenarioOptions.value.find((item) => item.value === option.value)
  if (match) {
    selectedScenario.value = match.scenario
    scenarioInput.value = match.label
    offset.value = 0
  }
}
function selectPerson(kind: 'instructor' | 'participant', option: AutocompleteOption) {
  const match = (kind === 'instructor' ? instructorOptions : participantOptions).value.find(
    (item) => item.value === option.value,
  )
  if (!match) return
  if (kind === 'instructor') {
    selectedInstructor.value = match.user
    instructorInput.value = match.label
  } else {
    selectedParticipant.value = match.user
    participantInput.value = match.label
  }
  offset.value = 0
}
function reset() {
  completedFrom.value = ''
  completedTo.value = ''
  aircraftId.value = null
  scenarioInput.value = ''
  instructorInput.value = ''
  participantInput.value = ''
  selectedScenario.value = null
  selectedInstructor.value = null
  selectedParticipant.value = null
  limit.value = 20
  offset.value = 0
}
</script>
<template>
  <section class="flex flex-col gap-4">
    <div class="space-y-4 lg:mx-auto lg:w-max lg:max-w-full">
      <header class="space-y-1">
        <h1 class="text-2xl font-semibold tracking-tight text-foreground">Training sessions</h1>
      </header>
      <div class="grid gap-4 lg:grid-cols-[auto_240px] lg:items-start lg:gap-3 2xl:gap-4">
        <div class="min-w-0 space-y-4">
          <section
            v-if="dateError"
            role="alert"
            class="rounded-2xl border border-line-danger bg-danger-soft px-4 py-3 text-sm text-danger"
          >
            {{ dateError }}
          </section>
          <section
            v-if="sessionsQuery.isError.value"
            role="alert"
            class="rounded-2xl border border-line-danger bg-danger-soft px-4 py-3 text-sm text-danger"
          >
            {{ errorMessage(sessionsQuery.error.value, 'Failed to load training sessions list.') }}
          </section>
          <div class="w-max max-w-full space-y-4">
            <TrainingSessionsList
              :aircraft-labels-by-id="aircraftLabels"
              :aircraft-colors-by-id="aircraftColors"
              :is-loading="sessionsQuery.isLoading.value"
              :sessions="sessionsQuery.data.value?.items ?? []"
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
        <aside class="lg:sticky lg:top-0 lg:self-start">
          <div class="space-y-4">
            <TrainingSessionsFilters
              :completed-from-value="completedFrom"
              :completed-to-value="completedTo"
              :aircraft-id-value="aircraftId"
              :aircraft-options="aircraftOptions"
              :scenario-value="scenarioInput"
              :scenario-options="scenarioOptions"
              :instructor-value="instructorInput"
              :instructor-options="instructorOptions"
              :participant-value="participantInput"
              :participant-options="participantOptions"
              :is-aircraft-loading="aircraftQuery.isLoading.value"
              :is-scenario-loading="scenariosQuery.isLoading.value"
              :is-instructor-loading="instructors.isLoading.value"
              :is-participant-loading="participants.isLoading.value"
              :limit-value="limit"
              @completed-from-change="
                ($event) => {
                  completedFrom = $event
                  offset = 0
                }
              "
              @completed-to-change="
                ($event) => {
                  completedTo = $event
                  offset = 0
                }
              "
              @aircraft-change="changeAircraft"
              @scenario-value-change="changeScenario"
              @scenario-select="selectScenario"
              @scenario-clear="
                () => {
                  selectedScenario = null
                  scenarioInput = ''
                  offset = 0
                }
              "
              @instructor-value-change="changePerson('instructor', $event)"
              @instructor-select="selectPerson('instructor', $event)"
              @instructor-clear="
                () => {
                  selectedInstructor = null
                  instructorInput = ''
                  offset = 0
                }
              "
              @participant-value-change="changePerson('participant', $event)"
              @participant-select="selectPerson('participant', $event)"
              @participant-clear="
                () => {
                  selectedParticipant = null
                  participantInput = ''
                  offset = 0
                }
              "
              @limit-change="
                ($event) => {
                  limit = $event
                  offset = 0
                }
              "
              @reset="reset"
            />
            <section
              v-for="message in lookupErrors"
              :key="message"
              class="rounded-2xl border border-line-warning bg-warning-soft px-4 py-3 text-sm text-warning"
            >
              {{ message }}
            </section>
          </div>
        </aside>
      </div>
    </div>
  </section>
</template>
