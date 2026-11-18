<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useQuery } from '@tanstack/vue-query'
import { commanderApi } from '@/entities/commander/api'
import { commanderKeys } from '@/entities/commander/queryKeys'
import type {
  TrainingSessionDetailAssessment,
  TrainingSessionDetailParticipant,
} from '@/entities/commander/types'
import { useSessionStore } from '@/entities/session/store'
import { useSessionScope } from '@/entities/session/useSessionScope'
import TrainingSessionAiReviewPanel from '@/features/training-session-detail/ui/TrainingSessionAiReviewPanel.vue'
import TrainingSessionCrewSummary from '@/features/training-session-detail/ui/TrainingSessionCrewSummary.vue'
import TrainingSessionDayPlan from '@/features/training-session-detail/ui/TrainingSessionDayPlan.vue'
import TrainingSessionSelectedPilotCard from '@/features/training-session-detail/ui/TrainingSessionSelectedPilotCard.vue'
import CrewCard from '@/features/training-session-detail/ui/CrewCard.vue'
import {
  createReportPrintWindow,
  openPdfPrintDialog,
} from '@/features/training-session-detail/lib/reportPrinting'
import { formatTrainingSessionTimestamp } from '@/features/training-sessions/lib/trainingSessionPresentation'
import { getErrorMessage } from '@/shared/lib/errorMessage'
import AircraftChip from '@/shared/ui/chips/AircraftChip.vue'
const route = useRoute(),
  router = useRouter(),
  auth = useSessionStore(),
  scope = useSessionScope()
const id = computed(() => Number(route.params.trainingSessionId))
const validId = computed(
  () =>
    /^\d+$/.test(String(route.params.trainingSessionId)) &&
    Number.isSafeInteger(id.value) &&
    id.value > 0,
)
const detailQuery = useQuery({
  queryKey: computed(() => [
    ...commanderKeys.root(scope.value),
    'training-sessions',
    id.value,
    'detail',
  ]),
  queryFn: ({ signal }) => commanderApi.getTrainingSessionDetail(id.value, signal),
  enabled: computed(() => auth.isReady && validId.value),
  retry: 0,
})
const aircraftQuery = useQuery({
  queryKey: computed(() => commanderKeys.aircraft(scope.value)),
  queryFn: ({ signal }) => commanderApi.listAircraft(signal),
  enabled: computed(() => auth.isReady),
  retry: 0,
})
const detail = detailQuery.data
const training = computed(() => detail.value?.session)
const selectedId = ref<number | null>(null),
  tab = ref<'comments' | 'ai-review'>('comments')
const printingId = ref<number | null>(null),
  printError = ref<string | null>(null)
const navigationState = computed(() => {
  void route.fullPath
  return router.options.history.state
})
const backLabel = computed(() =>
  typeof navigationState.value.backLabel === 'string'
    ? navigationState.value.backLabel
    : 'Back to training sessions',
)
function goBack() {
  const candidate = navigationState.value.backTo
  const backTo =
    typeof candidate === 'string' &&
    /^\/(?:pilots|training-sessions)(?:\/[^?#]*)?(?:[?#].*)?$/.test(candidate)
      ? candidate
      : '/training-sessions'
  if (candidate === backTo && navigationState.value.back === backTo) router.back()
  else void router.push(backTo)
}
watch(id, () => {
  selectedId.value = null
  tab.value = 'comments'
  printError.value = null
  printingId.value = null
})
const assessment = computed(
  () =>
    detail.value?.assessments.find((item) => item.id === selectedId.value) ??
    detail.value?.assessments[0] ??
    null,
)
const participants = computed<TrainingSessionDetailParticipant[]>(() =>
  detail.value?.participants?.length
    ? detail.value.participants
    : (detail.value?.assessments ?? [])
        .filter((item) => item.trainingRole === 'cm1' || item.trainingRole === 'cm2')
        .map((item) => ({
          assessmentId: item.id,
          pilotId: item.pilotId,
          firstName: item.pilotFirstName,
          lastName: item.pilotLastName,
          photoUrl: null,
          initialCrewSlot: item.trainingRole === 'cm1' ? 'CM1' : 'CM2',
          finalCrewSlot: item.trainingRole === 'cm1' ? 'CM1' : 'CM2',
          pfDurationMs: 0,
          pmDurationMs: 0,
        })),
)
const cm1 = computed(() => participants.value.find((p) => p.finalCrewSlot === 'CM1') ?? null)
const cm2 = computed(() => participants.value.find((p) => p.finalCrewSlot === 'CM2') ?? null)
const cm1Assessment = computed(
  () =>
    detail.value?.assessments.find((item) =>
      cm1.value ? item.id === cm1.value.assessmentId : item.trainingRole === 'cm1',
    ) ?? null,
)
const cm2Assessment = computed(
  () =>
    detail.value?.assessments.find((item) =>
      cm2.value ? item.id === cm2.value.assessmentId : item.trainingRole === 'cm2',
    ) ?? null,
)
const projection = computed(() => detail.value?.crewRuntime?.projectionSource ?? 'LEGACY_PLANNED')
const swapAvailable = computed(
  () => detail.value?.crewRuntime != null && Object.hasOwn(detail.value.crewRuntime, 'latestSwap'),
)
const relatedDays = computed(() => {
  const session = training.value
  if (!session) return []
  return [
    ...(session.dayIndex != null
      ? [
          {
            id: session.id,
            title: session.dayTitle ?? session.title,
            dayIndex: session.dayIndex,
            isCurrent: true,
          },
        ]
      : []),
    ...session.previousDays.map((day) => ({ ...day, isCurrent: false })),
  ].sort((a, b) =>
    a.dayIndex != null && b.dayIndex != null
      ? b.dayIndex - a.dayIndex
      : a.dayIndex != null
        ? -1
        : b.dayIndex != null
          ? 1
          : a.title.localeCompare(b.title),
  )
})
const aircraftColor = computed(
  () =>
    aircraftQuery.data.value?.find((aircraft) => aircraft.id === training.value?.aircraftId)
      ?.colorHex ?? null,
)
const backClass =
  'inline-flex h-10 items-center justify-center rounded-xl border border-line-strong bg-surface px-4 text-sm font-semibold text-foreground-secondary transition hover:border-line-emphasis hover:bg-surface-subtle hover:text-foreground-inverse'
const dayClass =
  'inline-flex h-8 min-w-[55px] shrink-0 items-center justify-center rounded-full border px-3 py-1.5 text-xs font-semibold transition hover:border-line-emphasis hover:bg-surface-subtle hover:text-foreground-inverse'
function openDay(event: MouseEvent, target: number) {
  if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button !== 0) return
  event.preventDefault()
  void router.push({
    path: `/training-sessions/${target}`,
    state: { backTo: route.path, backLabel: 'Back to training session' },
  })
}
async function printReport(selected: TrainingSessionDetailAssessment) {
  if (!training.value || printingId.value !== null) return
  const sessionId = training.value.id
  printError.value = null
  printingId.value = selected.id
  const printWindow = createReportPrintWindow()
  try {
    const blob = await commanderApi.downloadTrainingSessionAssessmentReport(sessionId, selected.id)
    openPdfPrintDialog(
      blob,
      `training-report-${sessionId}-${selected.trainingRole}.pdf`,
      printWindow,
    )
  } catch (error) {
    printWindow?.close()
    if (id.value === sessionId)
      printError.value = getErrorMessage(error, 'Failed to open training report PDF.')
  } finally {
    if (id.value === sessionId) printingId.value = null
  }
}
</script>
<template>
  <section class="space-y-4">
    <button type="button" :class="backClass" @click="goBack">{{ backLabel }}</button>
    <section
      v-if="!validId || detailQuery.isError.value"
      role="alert"
      class="rounded-2xl border border-line-danger bg-danger-soft px-4 py-3 text-sm text-danger"
    >
      {{
        !validId
          ? 'Training session id is invalid.'
          : getErrorMessage(detailQuery.error.value, 'Failed to load training session detail.')
      }}
    </section>
    <template v-else-if="!detail || !training"
      ><section
        aria-label="Loading training session"
        class="h-56 animate-pulse rounded-[28px] bg-surface-muted" />
      <div class="h-[900px] animate-pulse rounded-[28px] bg-surface-muted"
    /></template>
    <template v-else>
      <section class="rounded-[28px] border border-line bg-surface p-5 shadow-sm">
        <div class="overflow-x-auto">
          <div
            class="grid w-max grid-cols-[190px_220px_220px_220px] grid-rows-[auto_auto] items-start gap-x-4 gap-y-3 px-4 py-4"
          >
            <div class="row-span-2 space-y-1">
              <p class="text-xs font-medium text-foreground-secondary">
                {{ formatTrainingSessionTimestamp(training.completedAt) }}
              </p>
              <h1 class="truncate text-base font-semibold text-foreground" :title="training.title">
                {{ training.title }}
              </h1>
              <p class="text-xs text-foreground-secondary">Location</p>
              <AircraftChip
                :color-hex="aircraftColor"
                class="h-8 min-w-[55px] justify-center px-3 py-1.5 text-xs"
                :title="training.aircraftCode ?? '—'"
                ><span class="truncate">{{ training.aircraftCode ?? '—' }}</span></AircraftChip
              >
            </div>
            <CrewCard
              label="Instructor"
              :first-name="training.instructorFirstName"
              :last-name="training.instructorLastName"
              :photo-url="training.instructorPhotoUrl"
              fallback="Unassigned"
              is-disabled
            />
            <CrewCard
              label="Participant · current CM1"
              :first-name="cm1?.firstName ?? training.cm1FirstName"
              :last-name="cm1?.lastName ?? training.cm1LastName"
              :photo-url="cm1?.photoUrl ?? training.cm1PhotoUrl"
              fallback="Unassigned"
              :is-active="assessment?.id === cm1Assessment?.id"
              :is-disabled="!cm1Assessment"
              @select="cm1Assessment && (selectedId = cm1Assessment.id)"
            />
            <CrewCard
              label="Participant · current CM2"
              :first-name="cm2?.firstName ?? training.cm2FirstName"
              :last-name="cm2?.lastName ?? training.cm2LastName"
              :photo-url="cm2?.photoUrl ?? training.cm2PhotoUrl"
              fallback="Unassigned"
              :is-active="assessment?.id === cm2Assessment?.id"
              :is-disabled="!cm2Assessment"
              @select="cm2Assessment && (selectedId = cm2Assessment.id)"
            />
            <div class="col-[2/5] flex min-w-max flex-nowrap items-center gap-2 self-end">
              <template v-for="day in relatedDays" :key="day.id"
                ><span
                  v-if="day.isCurrent"
                  :title="day.title"
                  :class="[
                    dayClass,
                    'border-line-emphasis bg-surface-subtle text-foreground-inverse',
                  ]"
                  >{{ day.dayIndex != null ? `Day ${day.dayIndex}` : day.title }}</span
                ><a
                  v-else
                  :href="router.resolve(`/training-sessions/${day.id}`).href"
                  :title="`Open ${day.title}`"
                  :class="[dayClass, 'border-line bg-surface-muted text-foreground']"
                  @click="openDay($event, day.id)"
                  >{{ day.dayIndex != null ? `Day ${day.dayIndex}` : day.title }}</a
                ></template
              >
              <p v-if="!relatedDays.length" class="text-xs text-foreground-secondary">
                Single-day training group
              </p>
            </div>
          </div>
        </div>
        <TrainingSessionCrewSummary
          :participants="participants"
          :modules="detail.modules"
          :projection-source="projection"
          :latest-swap="detail.crewRuntime?.latestSwap ?? null"
          :latest-swap-projection-available="swapAvailable"
        />
        <section
          v-if="training.notes?.trim()"
          class="mt-5 border-t border-line pt-5"
          aria-labelledby="training-notes-heading"
        >
          <h2 id="training-notes-heading" class="text-sm font-semibold text-foreground">
            Training notes
          </h2>
          <p class="mt-2 whitespace-pre-wrap text-sm leading-6 text-foreground-secondary">
            {{ training.notes }}
          </p>
        </section>
      </section>
      <TrainingSessionSelectedPilotCard
        :assessment="assessment"
        :active-tab="tab"
        :is-report-printing="printingId !== null"
        :report-print-error="printError"
        @tab-change="tab = $event"
        @print-report="printReport"
      />
      <div class="min-w-0">
        <TrainingSessionAiReviewPanel
          v-if="tab === 'ai-review'"
          :assessment="assessment"
        /><TrainingSessionDayPlan
          v-else
          :key="id"
          :modules="detail.modules"
          :participants="participants"
          :projection-source="projection"
          :selected-assessment="assessment"
        />
      </div>
    </template>
  </section>
</template>
