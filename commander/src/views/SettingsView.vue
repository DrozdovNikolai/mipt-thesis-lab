<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { commanderApi } from '@/entities/commander/api'
import { commanderKeys } from '@/entities/commander/queryKeys'
import type { CommanderFlightType } from '@/entities/commander/types'
import { useSessionStore } from '@/entities/session/store'
import { useSessionScope } from '@/entities/session/useSessionScope'
import { PRIVILEGES } from '@/entities/session/privileges'
import { getErrorMessage } from '@/shared/lib/errorMessage'
import {
  areThresholdDraftsEqual,
  buildThresholdDraft,
  buildThresholdsReplacePayload,
  countConfiguredThresholds,
  createFlightTypeDraft,
  normalizeFlightTypeName,
  pruneFlightTypeDraft,
  sortFlightTypesByName,
  type FlightTypeDraft,
} from '@/features/settings/lib/flightTypeDrafts'
import {
  clampFlightTypeNameInput,
  sanitizeFlightTypeThresholdInput,
} from '@/features/settings/lib/settingsConstraints'
import TrainingTypeDirectory from '@/features/settings/ui/TrainingTypeDirectory.vue'
import TrainingTypeEditor from '@/features/settings/ui/TrainingTypeEditor.vue'
const cache = useQueryClient(),
  session = useSessionStore(),
  scope = useSessionScope()
const canWrite = computed(() => session.hasPrivilege(PRIVILEGES.PILOTS_WRITE))
const typesKey = computed(() => commanderKeys.flightTypes(scope.value))
const typesQuery = useQuery({
  queryKey: typesKey,
  queryFn: () => commanderApi.listFlightTypes(),
  enabled: computed(() => session.isReady),
  retry: 0,
})
const competencesQuery = useQuery({
  queryKey: computed(() => commanderKeys.competences(scope.value)),
  queryFn: () => commanderApi.listCompetences(),
  enabled: computed(() => session.isReady),
  retry: 0,
})
const competences = computed(() =>
  [...(competencesQuery.data.value ?? [])].sort(
    (a, b) => (a.orderIndex ?? 0) - (b.orderIndex ?? 0) || a.id - b.id,
  ),
)
const flightTypes = computed(() => sortFlightTypesByName(typesQuery.data.value ?? []))
const createName = ref(''),
  selectedId = ref<number | null>(null),
  search = ref('')
const drafts = reactive<Record<number, FlightTypeDraft>>({})
const validation = ref<string | null>(null)
const selected = computed(
  () =>
    flightTypes.value.find((item) => item.id === selectedId.value) ?? flightTypes.value[0] ?? null,
)
const draft = computed(() => (selected.value ? (drafts[selected.value.id] ?? null) : null))
const name = computed(() => (selected.value ? (draft.value?.name ?? selected.value.name) : ''))
const thresholds = computed(() =>
  selected.value ? (draft.value?.thresholds ?? buildThresholdDraft(selected.value.thresholds)) : {},
)
const configuredCount = computed(() =>
  countConfiguredThresholds(competences.value, thresholds.value),
)
const nameDirty = computed(() =>
  Boolean(selected.value && normalizeFlightTypeName(name.value) !== selected.value.name),
)
const thresholdsDirty = computed(() =>
  Boolean(
    selected.value && !areThresholdDraftsEqual(selected.value, thresholds.value, competences.value),
  ),
)
const fields = computed(() =>
  competences.value
    .filter((item) =>
      `${item.code} ${item.name}`.toLowerCase().includes(search.value.trim().toLowerCase()),
    )
    .map((item) => ({
      competenceId: item.id,
      code: item.code,
      name: item.name,
      description: item.description,
      value: thresholds.value[item.id] ?? '',
      isConfigured: Boolean(thresholds.value[item.id]?.trim()),
    })),
)
const directoryItems = computed(() =>
  flightTypes.value.map((item) => ({
    id: item.id,
    name: item.name,
    isMain: item.isMain,
    updatedAt: item.updatedAt,
    configuredThresholds: item.thresholds.length,
    totalCompetences: competences.value.length,
  })),
)
function upsert(item: CommanderFlightType) {
  cache.setQueryData<CommanderFlightType[]>(typesKey.value, (current) => {
    const previous = (current ?? []).map((old) =>
      item.isMain && old.id !== item.id ? { ...old, isMain: false } : old,
    )
    return sortFlightTypesByName(
      previous.some((old) => old.id === item.id)
        ? previous.map((old) => (old.id === item.id ? item : old))
        : [...previous, item],
    )
  })
  void cache.invalidateQueries({ queryKey: commanderKeys.compatibility(scope.value) })
}
function prune(item: CommanderFlightType, next: FlightTypeDraft) {
  const pruned = pruneFlightTypeDraft(item, next, competences.value)
  if (pruned) drafts[item.id] = pruned
  else delete drafts[item.id]
}
function updateDraft(update: (draft: FlightTypeDraft) => FlightTypeDraft) {
  if (!selected.value || !canWrite.value || busy.value) return
  prune(selected.value, update(drafts[selected.value.id] ?? createFlightTypeDraft(selected.value)))
}
const create = useMutation({
  mutationFn: (name: string) => commanderApi.createFlightType({ name }),
  onSuccess: (item) => {
    upsert(item)
    createName.value = ''
    selectedId.value = item.id
  },
})
const saveName = useMutation({
  mutationFn: ({ id, name }: { id: number; name: string }) =>
    commanderApi.updateFlightType(id, { name }),
  onSuccess: (item) => {
    upsert(item)
    const existing = drafts[item.id]
    if (existing) prune(item, { name: item.name, thresholds: existing.thresholds })
  },
})
const saveThresholds = useMutation({
  mutationFn: ({ id, values }: { id: number; values: Record<number, string> }) => {
    const { payload, validationMessage } = buildThresholdsReplacePayload(competences.value, values)
    if (!payload) throw new Error(validationMessage ?? 'Invalid threshold values.')
    return commanderApi.replaceFlightTypeThresholds(id, payload)
  },
  onSuccess: (item) => {
    upsert(item)
    validation.value = null
    const existing = drafts[item.id]
    if (existing)
      prune(item, { name: existing.name, thresholds: buildThresholdDraft(item.thresholds) })
  },
})
const remove = useMutation({
  mutationFn: (id: number) => commanderApi.deleteFlightType(id),
  onSuccess: (_, id) => {
    cache.setQueryData<CommanderFlightType[]>(typesKey.value, (current) =>
      (current ?? []).filter((item) => item.id !== id),
    )
    delete drafts[id]
    if (selectedId.value === id) selectedId.value = null
    validation.value = null
    void cache.invalidateQueries({ queryKey: commanderKeys.compatibility(scope.value) })
  },
})
const makeMain = useMutation({
  mutationFn: (id: number) => commanderApi.updateFlightType(id, { isMain: true }),
  onSuccess: upsert,
})
const busy = computed(
  () =>
    create.isPending.value ||
    saveName.isPending.value ||
    saveThresholds.isPending.value ||
    remove.isPending.value ||
    makeMain.isPending.value,
)
const error = (value: unknown) => getErrorMessage(value, 'Failed to load settings.')
const loadingError = computed(() =>
  [
    typesQuery.isError.value ? error(typesQuery.error.value) : null,
    competencesQuery.isError.value ? error(competencesQuery.error.value) : null,
  ]
    .filter(Boolean)
    .join(' '),
)
const actionError = computed(
  () =>
    [saveName, saveThresholds, makeMain, remove].find((mutation) => mutation.isError.value)?.error
      .value,
)
function resetActions() {
  if (busy.value) return
  saveName.reset()
  saveThresholds.reset()
  makeMain.reset()
  remove.reset()
  validation.value = null
}
function selectType(id: number) {
  selectedId.value = id
  resetActions()
}
function changeName(value: string) {
  resetActions()
  updateDraft((draft) => ({ ...draft, name: clampFlightTypeNameInput(value) }))
}
function changeThreshold(id: number, value: string) {
  resetActions()
  updateDraft((draft) => ({
    ...draft,
    thresholds: { ...draft.thresholds, [id]: sanitizeFlightTypeThresholdInput(value) },
  }))
}
function createType() {
  const value = normalizeFlightTypeName(createName.value)
  if (canWrite.value && !busy.value && value) create.mutate(value)
}
function submitName() {
  const value = normalizeFlightTypeName(name.value)
  if (canWrite.value && !busy.value && selected.value && nameDirty.value && value)
    saveName.mutate({ id: selected.value.id, name: value })
}
function submitThresholds() {
  if (
    !canWrite.value ||
    busy.value ||
    !selected.value ||
    !thresholdsDirty.value ||
    competencesQuery.isError.value ||
    competencesQuery.isPending.value
  )
    return
  const { validationMessage } = buildThresholdsReplacePayload(competences.value, thresholds.value)
  if (validationMessage) {
    validation.value = validationMessage
    return
  }
  saveThresholds.mutate({ id: selected.value.id, values: { ...thresholds.value } })
}
function deleteType() {
  if (
    canWrite.value &&
    !busy.value &&
    selected.value &&
    window.confirm(`Delete training type "${selected.value.name}"? This cannot be undone.`)
  )
    remove.mutate(selected.value.id)
}
function makeMainType() {
  if (canWrite.value && !busy.value && selected.value && !selected.value.isMain) {
    resetActions()
    makeMain.mutate(selected.value.id)
  }
}
function resetDraft() {
  if (selected.value && !busy.value) {
    delete drafts[selected.value.id]
    validation.value = null
  }
}
</script>
<template>
  <section class="flex flex-col gap-4">
    <header class="space-y-2">
      <h1 class="text-2xl font-semibold tracking-tight text-foreground">Settings</h1>
      <p class="max-w-3xl text-sm text-foreground">
        Main threshold is used for analytics of one specific pilot. Additional thresholds are kept
        for comparing and summing scores between two pilots.
      </p>
    </header>
    <section
      v-if="!canWrite"
      class="rounded-2xl border border-line bg-surface px-4 py-3 text-sm text-foreground-secondary"
    >
      You have read-only access to training types.
    </section>
    <section
      v-if="loadingError"
      role="alert"
      class="rounded-2xl border border-line-danger bg-danger-soft px-4 py-3 text-sm text-danger"
    >
      {{ loadingError }}
    </section>
    <div class="grid gap-4 xl:grid-cols-[360px_minmax(0,1fr)]">
      <TrainingTypeDirectory
        :can-write="canWrite"
        :can-create="Boolean(normalizeFlightTypeName(createName)) && !busy"
        :create-name="createName"
        :create-error-message="create.isError.value ? error(create.error.value) : null"
        :is-creating="create.isPending.value"
        :is-loading="typesQuery.isLoading.value"
        :items="directoryItems"
        :selected-id="selected?.id ?? null"
        @create="createType"
        @create-name-change="
          ($event) => {
            create.reset()
            createName = clampFlightTypeNameInput($event)
          }
        "
        @select="selectType"
      />
      <TrainingTypeEditor
        :can-write="canWrite"
        :busy="busy"
        :action-error-message="actionError ? error(actionError) : null"
        :can-save-name="nameDirty && Boolean(normalizeFlightTypeName(name))"
        :competence-search="search"
        :configured-threshold-count="configuredCount"
        :filtered-fields="fields"
        :flight-type="selected"
        :has-unsaved-changes="nameDirty || thresholdsDirty"
        :is-deleting="remove.isPending.value"
        :is-loading="typesQuery.isLoading.value || competencesQuery.isLoading.value"
        :is-making-main="makeMain.isPending.value"
        :is-saving-name="saveName.isPending.value"
        :is-saving-thresholds="saveThresholds.isPending.value"
        :is-thresholds-dirty="thresholdsDirty"
        :threshold-validation-message="validation"
        :total-competence-count="competences.length"
        :training-type-name="name"
        @competence-search-change="search = $event"
        @delete="deleteType"
        @make-main="makeMainType"
        @name-change="changeName"
        @reset="resetDraft"
        @save-name="submitName"
        @save-thresholds="submitThresholds"
        @threshold-change="changeThreshold"
      />
    </div>
  </section>
</template>
