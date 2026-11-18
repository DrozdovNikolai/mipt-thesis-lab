<script setup lang="ts">
import type { CommanderFlightType } from '@/entities/commander/types'
import {
  FLIGHT_TYPE_NAME_MAX_LENGTH,
  FLIGHT_TYPE_THRESHOLD_INPUT_MAX_LENGTH,
  FLIGHT_TYPE_THRESHOLD_MAX_DECIMAL_DIGITS,
  FLIGHT_TYPE_THRESHOLD_MAX_INTEGER_DIGITS,
  FLIGHT_TYPE_THRESHOLD_MAX_VALUE,
} from '../lib/settingsConstraints'
defineProps<{
  canWrite: boolean
  busy: boolean
  actionErrorMessage: string | null
  canSaveName: boolean
  competenceSearch: string
  configuredThresholdCount: number
  filteredFields: {
    competenceId: number
    code: string
    name: string
    description: string | null
    value: string
    isConfigured: boolean
  }[]
  flightType: CommanderFlightType | null
  hasUnsavedChanges: boolean
  isDeleting: boolean
  isLoading: boolean
  isMakingMain: boolean
  isSavingName: boolean
  isSavingThresholds: boolean
  isThresholdsDirty: boolean
  thresholdValidationMessage: string | null
  totalCompetenceCount: number
  trainingTypeName: string
}>()
const emit = defineEmits<{
  competenceSearchChange: [value: string]
  delete: []
  makeMain: []
  nameChange: [value: string]
  reset: []
  saveName: []
  saveThresholds: []
  thresholdChange: [id: number, value: string]
}>()
const inputClass =
  'h-11 w-full rounded-2xl border border-line bg-surface px-4 text-sm text-foreground outline-none transition placeholder:text-foreground focus:border-line-emphasis focus:ring-2 focus:ring-focus'
const primaryClass =
  'inline-flex h-11 items-center justify-center rounded-2xl border border-line-emphasis bg-surface px-4 text-sm font-semibold text-foreground transition hover:border-line-emphasis hover:bg-surface-subtle hover:text-foreground-inverse disabled:cursor-not-allowed disabled:opacity-55'
const secondaryClass =
  'inline-flex h-11 items-center justify-center rounded-2xl border border-line-strong bg-surface px-4 text-sm font-semibold text-foreground-secondary transition hover:border-line-emphasis hover:bg-surface-subtle hover:text-foreground-inverse disabled:cursor-not-allowed disabled:opacity-55'
const pattern = `^\\d{0,${FLIGHT_TYPE_THRESHOLD_MAX_INTEGER_DIGITS}}(\\.\\d{0,${FLIGHT_TYPE_THRESHOLD_MAX_DECIMAL_DIGITS}})?$`
const formatTimestamp = (value: string) =>
  new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(
    new Date(value),
  )
</script>
<template>
  <section
    v-if="isLoading && !flightType"
    class="space-y-4 rounded-[28px] border border-line bg-surface p-5 shadow-sm"
  >
    <div class="h-36 animate-pulse rounded-[24px] bg-surface-subtle" />
    <div class="grid gap-3 xl:grid-cols-2">
      <div
        v-for="index in 4"
        :key="index"
        class="h-40 animate-pulse rounded-[24px] bg-surface-subtle"
      />
    </div>
  </section>
  <section
    v-else-if="!flightType"
    class="rounded-[28px] border border-dashed border-line-strong bg-surface px-6 py-16 text-center shadow-sm"
  >
    <div class="mx-auto max-w-md space-y-3">
      <div
        class="inline-flex rounded-full border border-line bg-surface-subtle px-3 py-1 text-xs font-semibold uppercase tracking-[0.16em] text-foreground-secondary"
      >
        No selection
      </div>
      <h2 class="text-2xl font-semibold tracking-tight text-foreground">
        Create a training type to configure thresholds
      </h2>
      <p class="text-sm text-foreground">
        Once a training type exists, you can define the compatibility threshold for every competence
        from this panel.
      </p>
    </div>
  </section>
  <section v-else class="rounded-[28px] border border-line bg-surface p-5 shadow-sm">
    <header class="rounded-[24px] border border-line bg-surface-muted px-5 py-5 shadow-sm">
      <div class="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
        <div class="space-y-2">
          <div
            class="inline-flex rounded-full border border-line bg-surface px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.18em] text-foreground-secondary"
          >
            Active training type
          </div>
          <div>
            <h2 class="text-2xl font-semibold tracking-tight text-foreground">
              {{ flightType.name }}
            </h2>
            <p class="mt-1 text-sm text-foreground-secondary">
              Threshold coverage {{ configuredThresholdCount }}/{{
                totalCompetenceCount || configuredThresholdCount
              }}
            </p>
            <p class="mt-2 max-w-2xl text-sm text-foreground">
              Main threshold is used for analytics of one specific pilot. Other thresholds are used
              when comparing and summing scores between two pilots.
            </p>
          </div>
        </div>
        <div class="flex flex-wrap items-center gap-2">
          <span
            v-if="flightType.isMain"
            class="rounded-full border border-line-emphasis bg-surface px-3 py-1 text-xs font-semibold text-foreground"
            >Main threshold</span
          ><span
            class="rounded-full border border-line bg-surface px-3 py-1 text-xs font-semibold text-foreground-secondary"
            >Updated {{ formatTimestamp(flightType.updatedAt) }}</span
          ><span
            v-if="hasUnsavedChanges"
            class="rounded-full border border-line-warning bg-warning-soft px-3 py-1 text-xs font-semibold text-warning"
            >Unsaved changes</span
          ><span
            v-else
            class="rounded-full border border-line-success bg-success-soft px-3 py-1 text-xs font-semibold text-success"
            >Up to date</span
          >
        </div>
      </div>
      <div class="mt-5 grid gap-3 xl:grid-cols-[minmax(0,1fr)_auto_auto_auto]">
        <label class="flex flex-col gap-1.5"
          ><span class="text-xs font-semibold uppercase tracking-wide text-foreground-secondary"
            >Training type name</span
          ><input
            :value="trainingTypeName"
            :disabled="!canWrite || busy"
            :class="inputClass"
            placeholder="Training type name"
            :maxlength="FLIGHT_TYPE_NAME_MAX_LENGTH"
            @input="emit('nameChange', ($event.target as HTMLInputElement).value)" /></label
        ><button
          type="button"
          :disabled="!canWrite || !canSaveName || busy"
          :class="primaryClass"
          @click="emit('saveName')"
        >
          {{ isSavingName ? 'Saving...' : 'Save name' }}</button
        ><button
          type="button"
          :disabled="!canWrite || flightType.isMain || busy"
          :class="secondaryClass"
          @click="emit('makeMain')"
        >
          {{
            flightType.isMain ? 'Main threshold' : isMakingMain ? 'Updating...' : 'Make main'
          }}</button
        ><button
          type="button"
          :disabled="!canWrite || busy"
          class="inline-flex h-11 items-center justify-center rounded-2xl border border-line-danger bg-danger-soft px-4 text-sm font-semibold text-danger transition hover:border-line-danger-emphasis hover:bg-danger-soft hover:text-danger disabled:cursor-not-allowed disabled:opacity-55"
          @click="emit('delete')"
        >
          {{ isDeleting ? 'Deleting...' : 'Delete' }}
        </button>
      </div>
    </header>
    <div
      v-if="actionErrorMessage"
      role="alert"
      class="mt-4 rounded-2xl border border-line-danger bg-danger-soft px-4 py-3 text-sm text-danger"
    >
      {{ actionErrorMessage }}
    </div>
    <div
      v-if="thresholdValidationMessage"
      role="alert"
      class="mt-4 rounded-2xl border border-line-warning bg-warning-soft px-4 py-3 text-sm text-warning"
    >
      {{ thresholdValidationMessage }}
    </div>
    <section class="mt-5 rounded-[24px] border border-line bg-surface-muted p-4">
      <div class="flex flex-col gap-3 xl:flex-row xl:items-end xl:justify-between">
        <div class="grid flex-1 gap-3 xl:grid-cols-[minmax(0,1fr)_auto_auto]">
          <label class="flex flex-col gap-1.5"
            ><span class="text-xs font-semibold uppercase tracking-wide text-foreground"
              >Filter competences</span
            ><input
              :value="competenceSearch"
              placeholder="Search by code or name"
              :class="inputClass"
              @input="emit('competenceSearchChange', ($event.target as HTMLInputElement).value)"
          /></label>
        </div>
        <div class="flex flex-wrap items-center gap-2">
          <button
            type="button"
            :disabled="!hasUnsavedChanges || busy"
            :class="secondaryClass"
            @click="emit('reset')"
          >
            Reset draft</button
          ><button
            type="button"
            :disabled="!canWrite || !isThresholdsDirty || busy || isLoading"
            :class="primaryClass"
            @click="emit('saveThresholds')"
          >
            {{ isSavingThresholds ? 'Saving...' : 'Save thresholds' }}
          </button>
        </div>
      </div>
      <div class="mt-4 grid gap-3 xl:grid-cols-2">
        <div
          v-if="!filteredFields.length"
          class="rounded-[22px] border border-dashed border-line-strong bg-surface px-4 py-10 text-center text-sm text-foreground xl:col-span-2"
        >
          No competences match the current filter.
        </div>
        <article
          v-for="field in filteredFields"
          :key="field.competenceId"
          class="rounded-[22px] border border-line bg-surface p-4 transition hover:border-line-strong"
        >
          <div class="flex items-start justify-between gap-3">
            <div class="min-w-0">
              <div
                class="inline-flex rounded-full bg-foreground-pilot-badge px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide text-surface"
              >
                {{ field.code }}
              </div>
              <h3 class="mt-3 text-base font-semibold tracking-tight text-foreground">
                {{ field.name }}
              </h3>
              <p v-if="field.description" class="mt-1 text-sm text-foreground">
                {{ field.description }}
              </p>
            </div>
            <span
              :class="
                field.isConfigured
                  ? 'rounded-full bg-success-soft px-3 py-1 text-[11px] font-semibold uppercase tracking-wide text-success'
                  : 'rounded-full border border-line bg-surface px-3 py-1 text-[11px] font-semibold uppercase tracking-wide text-foreground'
              "
              >{{ field.isConfigured ? 'Configured' : 'Not set' }}</span
            >
          </div>
          <div class="mt-4 flex items-end gap-3">
            <label class="flex flex-1 flex-col gap-1.5"
              ><span class="text-xs font-semibold uppercase tracking-wide text-foreground"
                >Threshold</span
              ><input
                type="text"
                inputmode="decimal"
                autocomplete="off"
                :value="field.value"
                :disabled="!canWrite || busy"
                :placeholder="`0 - ${FLIGHT_TYPE_THRESHOLD_MAX_VALUE}`"
                :class="inputClass"
                :maxlength="FLIGHT_TYPE_THRESHOLD_INPUT_MAX_LENGTH"
                :pattern="pattern"
                @input="
                  emit(
                    'thresholdChange',
                    field.competenceId,
                    ($event.target as HTMLInputElement).value,
                  )
                " /></label
            ><button
              v-if="field.value"
              type="button"
              :disabled="!canWrite || busy"
              :class="secondaryClass"
              @click="emit('thresholdChange', field.competenceId, '')"
            >
              Clear
            </button>
          </div>
        </article>
      </div>
    </section>
  </section>
</template>
