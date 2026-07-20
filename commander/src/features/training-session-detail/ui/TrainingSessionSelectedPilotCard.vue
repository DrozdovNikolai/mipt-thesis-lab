<script setup lang="ts">
import { computed } from 'vue'
import type { TrainingSessionDetailAssessment } from '@/entities/commander/types'
import { getPersonLabel } from '@/features/training-sessions/lib/trainingSessionPresentation'
const props = defineProps<{
  assessment: TrainingSessionDetailAssessment | null
  activeTab: 'comments' | 'ai-review'
  isReportPrinting?: boolean
  reportPrintError?: string | null
}>()
const emit = defineEmits<{
  tabChange: [tab: 'comments' | 'ai-review']
  printReport: [assessment: TrainingSessionDetailAssessment]
}>()
const label = computed(() =>
  props.assessment
    ? getPersonLabel(
        props.assessment.pilotFirstName,
        props.assessment.pilotLastName,
        'Unassigned pilot',
      )
    : '',
)
const reports = computed(() =>
  [...(props.assessment?.finalReports ?? [])].sort(
    (a, b) => a.orderIndex - b.orderIndex || a.competenceId - b.competenceId,
  ),
)
const actionClass =
  'inline-flex h-10 items-center justify-center rounded-xl border border-line-strong bg-surface px-4 text-sm font-semibold text-foreground-secondary transition hover:border-line-emphasis hover:bg-surface-subtle hover:text-foreground-inverse'
const tabClass = (active: boolean) => [
  'inline-flex h-10 items-center justify-center rounded-xl border px-4 text-sm font-semibold transition',
  active
    ? 'border-line-emphasis bg-surface-subtle text-foreground-inverse'
    : 'border-line-strong bg-surface text-foreground-secondary hover:border-line-emphasis hover:bg-surface-subtle hover:text-foreground-inverse',
]
</script>
<template>
  <section
    v-if="!assessment"
    class="rounded-[28px] border border-dashed border-line-strong bg-surface p-5 shadow-sm"
  >
    <p class="text-sm text-foreground-secondary">
      Select a crew assessment to view pilot actions and final grades.
    </p>
  </section>
  <section v-else class="rounded-[28px] border border-line bg-surface p-5 shadow-sm">
    <div class="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
      <div class="min-w-0">
        <h2
          class="mt-2 truncate text-3xl font-semibold tracking-tight text-foreground"
          :title="label"
        >
          {{ label }}
        </h2>
      </div>
      <div class="flex w-full flex-wrap justify-end gap-2 lg:w-auto">
        <RouterLink
          v-if="assessment.pilotId"
          :to="`/pilots/${encodeURIComponent(assessment.pilotId)}/training-data`"
          target="_blank"
          rel="noreferrer"
          :class="actionClass"
          >Profile</RouterLink
        ><button v-else type="button" :class="actionClass" disabled>Profile</button>
        <button
          type="button"
          :class="actionClass"
          :disabled="isReportPrinting"
          @click="emit('printReport', assessment)"
        >
          {{ isReportPrinting ? 'Exporting' : 'Export PDF' }}
        </button>
        <button type="button" :class="actionClass">Scenario</button>
      </div>
    </div>
    <div
      v-if="reportPrintError"
      role="alert"
      class="mt-4 rounded-xl border border-line-danger bg-danger-soft px-4 py-3 text-sm text-danger"
    >
      {{ reportPrintError }}
    </div>
    <div class="mt-5 overflow-x-auto">
      <div v-if="reports.length" class="flex min-w-max items-center gap-2 whitespace-nowrap">
        <div
          v-for="report in reports"
          :key="report.id"
          class="inline-flex items-center gap-2 rounded-full border border-line bg-surface-muted px-3 py-2 text-sm"
        >
          <span class="font-semibold text-foreground">{{ report.competenceCode }}</span
          ><span class="font-semibold" :style="{ color: report.gradeColorHex ?? undefined }">{{
            report.gradeLabel ?? report.gradeCode
          }}</span>
        </div>
      </div>
      <p v-else class="text-sm text-foreground-secondary">
        No final grades were attached to this assessment.
      </p>
    </div>
    <div class="mt-5 flex flex-wrap justify-end gap-2">
      <button
        type="button"
        :class="tabClass(activeTab === 'comments')"
        @click="emit('tabChange', 'comments')"
      >
        Comments</button
      ><button
        type="button"
        :class="tabClass(activeTab === 'ai-review')"
        @click="emit('tabChange', 'ai-review')"
      >
        AI review
      </button>
    </div>
  </section>
</template>
