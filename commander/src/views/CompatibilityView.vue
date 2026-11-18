<script setup lang="ts">
import { ref } from 'vue'
import PilotCompatibilityPanel from '@/features/compatibility/ui/PilotCompatibilityPanel.vue'
const date = ref('')
</script>
<template>
  <section class="flex flex-col gap-4">
    <header class="space-y-1">
      <h1 class="text-2xl font-semibold tracking-tight text-foreground">Compatibility</h1>
      <p class="max-w-3xl text-sm text-foreground">
        Compare two crew members against a training type and inspect which competence thresholds
        make the pairing compatible or incompatible.
      </p>
    </header>
    <section class="rounded-[28px] border border-line bg-surface p-5 shadow-sm">
      <div class="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div class="space-y-2">
          <div
            class="inline-flex rounded-full bg-surface-subtle px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.18em] text-foreground-inverse"
          >
            Filter
          </div>
          <div>
            <h2 class="text-lg font-semibold tracking-tight text-foreground">Comparison date</h2>
            <p class="max-w-2xl text-sm text-foreground">
              Leave the As of date empty to use the latest completed training records, or pin the
              comparison to a specific day.
            </p>
          </div>
        </div>
        <div class="grid gap-3 sm:grid-cols-[minmax(0,220px)_auto] lg:shrink-0">
          <label class="flex flex-col gap-1.5"
            ><span class="text-xs font-semibold uppercase tracking-wide text-foreground"
              >As of date</span
            ><input
              v-model="date"
              type="date"
              class="h-11 rounded-2xl border border-line bg-surface px-4 text-sm text-foreground outline-none transition focus:border-line-emphasis focus:ring-2 focus:ring-focus"
          /></label>
          <div class="flex flex-col gap-1.5">
            <span class="text-xs font-semibold uppercase tracking-wide text-foreground"
              >Actions</span
            ><button
              type="button"
              :disabled="!date"
              class="inline-flex h-11 items-center justify-center rounded-2xl border border-line-strong bg-surface-muted px-4 text-sm font-semibold text-foreground-secondary transition hover:border-line-emphasis hover:bg-surface-subtle hover:text-foreground-inverse disabled:cursor-not-allowed disabled:opacity-55"
              @click="date = ''"
            >
              Clear date
            </button>
          </div>
        </div>
      </div>
    </section>
    <PilotCompatibilityPanel :as-of-date="date" />
  </section>
</template>
