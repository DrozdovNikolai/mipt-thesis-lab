<script setup lang="ts">
import { FLIGHT_TYPE_NAME_MAX_LENGTH } from '../lib/settingsConstraints'
defineProps<{
  canCreate: boolean
  canWrite: boolean
  createName: string
  createErrorMessage: string | null
  isCreating: boolean
  isLoading: boolean
  items: {
    id: number
    name: string
    isMain: boolean
    updatedAt: string
    configuredThresholds: number
    totalCompetences: number
  }[]
  selectedId: number | null
}>()
const emit = defineEmits<{ create: []; createNameChange: [value: string]; select: [id: number] }>()
const formatTimestamp = (value: string) =>
  new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(
    new Date(value),
  )
</script>
<template>
  <section class="rounded-[28px] border border-line bg-surface p-5 shadow-sm">
    <div class="rounded-[24px] border border-line bg-surface-muted p-5">
      <div class="space-y-2">
        <div
          class="inline-flex rounded-full border border-line bg-surface px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.18em] text-foreground-secondary"
        >
          Settings
        </div>
        <h2 class="text-xl font-semibold tracking-tight text-foreground">Training types</h2>
        <p class="max-w-sm text-sm text-foreground">
          Create reusable training types and keep compatibility thresholds organized per competence.
        </p>
      </div>
      <form class="mt-5 space-y-3" @submit.prevent="emit('create')">
        <label class="flex flex-col gap-1.5"
          ><span class="text-xs font-semibold uppercase tracking-wide text-foreground"
            >New training type</span
          ><input
            :value="createName"
            :disabled="!canWrite || isCreating"
            placeholder="Line check, upgrade, recurrent..."
            class="h-11 w-full rounded-2xl border border-line bg-surface px-4 text-sm text-foreground outline-none transition placeholder:text-foreground focus:border-line-emphasis focus:ring-2 focus:ring-focus"
            :maxlength="FLIGHT_TYPE_NAME_MAX_LENGTH"
            @input="emit('createNameChange', ($event.target as HTMLInputElement).value)" /></label
        ><button
          type="submit"
          :disabled="!canCreate || isCreating || !canWrite"
          class="inline-flex h-11 items-center justify-center rounded-2xl border border-line-emphasis bg-surface px-4 text-sm font-semibold text-foreground transition hover:border-line-emphasis hover:bg-surface-subtle hover:text-foreground-inverse disabled:cursor-not-allowed disabled:opacity-60"
        >
          {{ isCreating ? 'Creating...' : 'Create training type' }}
        </button>
      </form>
      <div
        v-if="createErrorMessage"
        role="alert"
        class="mt-4 rounded-2xl border border-line-danger bg-danger-soft px-4 py-3 text-sm text-danger"
      >
        {{ createErrorMessage }}
      </div>
    </div>
    <div class="mt-5 space-y-3">
      <div class="flex items-center justify-between gap-3">
        <div>
          <h3 class="text-sm font-semibold uppercase tracking-[0.16em] text-foreground">
            Directory
          </h3>
          <p class="mt-1 text-sm text-foreground">
            Select a training type to edit its name and compatibility thresholds.
          </p>
        </div>
        <span
          class="rounded-full border border-line bg-surface px-3 py-1 text-xs font-semibold text-foreground-secondary"
          >{{ items.length }} total</span
        >
      </div>
      <div v-if="isLoading" class="space-y-2">
        <div
          v-for="index in 4"
          :key="index"
          class="h-24 animate-pulse rounded-2xl bg-surface-subtle"
        />
      </div>
      <div
        v-else-if="!items.length"
        class="rounded-2xl border border-dashed border-line-strong bg-surface-muted px-4 py-8 text-center text-sm text-foreground"
      >
        No training types yet. Create the first one from the panel above.
      </div>
      <div v-else class="space-y-2">
        <button
          v-for="item in items"
          :key="item.id"
          type="button"
          :class="
            item.id === selectedId
              ? 'w-full rounded-[22px] border border-line-emphasis bg-surface p-4 text-left text-foreground shadow-sm'
              : 'w-full rounded-[22px] border border-line bg-surface-muted p-4 text-left text-foreground transition hover:border-line-strong hover:bg-surface'
          "
          @click="emit('select', item.id)"
        >
          <div class="flex items-start justify-between gap-3">
            <div class="min-w-0">
              <h4 class="truncate text-base font-semibold tracking-tight">{{ item.name }}</h4>
              <div class="mt-1 flex flex-wrap items-center gap-2">
                <span
                  v-if="item.isMain"
                  class="rounded-full border border-line-emphasis bg-surface px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.16em] text-foreground"
                  >Main</span
                >
                <p
                  :class="
                    item.id === selectedId
                      ? 'text-sm text-foreground-secondary'
                      : 'text-sm text-foreground'
                  "
                >
                  Updated {{ formatTimestamp(item.updatedAt) }}
                </p>
              </div>
            </div>
            <span
              :class="[
                'rounded-full border bg-surface px-3 py-1 text-[11px] font-semibold uppercase tracking-wide text-foreground',
                item.id === selectedId ? 'border-line-emphasis' : 'border-line',
              ]"
              >{{
                item.totalCompetences
                  ? `${item.configuredThresholds}/${item.totalCompetences} thresholds`
                  : `${item.configuredThresholds} thresholds`
              }}</span
            >
          </div>
        </button>
      </div>
    </div>
  </section>
</template>
