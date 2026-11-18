<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import type { TrainingSessionListItem } from '@/entities/commander/types'
import {
  formatTrainingSessionTimestamp,
  getTrainingRoleBadgeLabel,
} from '../lib/trainingSessionPresentation'
import { formatTrainingDurationMs } from '@/features/training-session-detail/lib/crewTimelinePresentation'
import AircraftChip from '@/shared/ui/chips/AircraftChip.vue'
import StickyHorizontalScrollArea from '@/shared/ui/lists/StickyHorizontalScrollArea.vue'
import CrewMemberCell from './CrewMemberCell.vue'
type Row = TrainingSessionListItem & {
  trainingRole?: string | null
  finalCrewSlot?: 'CM1' | 'CM2' | null
  pfDurationMs?: number
  pmDurationMs?: number
  roleProjectionSource?: 'ACTUAL_TIMELINE' | 'LEGACY_PLANNED'
}
defineProps<{
  aircraftLabelsById: Record<number, string>
  aircraftColorsById: Record<number, string>
  isLoading: boolean
  sessions: Row[]
}>()
const route = useRoute()
const router = useRouter()
const sticky = computed(() => route.path === '/training-sessions')
const gridClass =
  'grid w-max grid-cols-[190px_220px_220px_220px] grid-rows-[auto_auto] items-start gap-x-4 gap-y-3 px-4 py-4'
const dayClass =
  'inline-flex h-8 min-w-[55px] shrink-0 items-center justify-center rounded-full border px-3 py-1.5 text-xs font-semibold transition hover:border-line-emphasis hover:bg-surface-subtle hover:text-foreground-inverse'
function roleLabel(session: Row) {
  return session.roleProjectionSource === 'ACTUAL_TIMELINE'
    ? `Current at completion ${session.finalCrewSlot ?? '—'} · PF ${formatTrainingDurationMs(session.pfDurationMs ?? 0)} · PM ${formatTrainingDurationMs(session.pmDurationMs ?? 0)}`
    : getTrainingRoleBadgeLabel(session.trainingRole)
}
function days(session: Row) {
  return [
    ...(session.dayTitle
      ? [
          {
            id: session.id,
            title: session.dayTitle,
            dayIndex: session.dayIndex ?? null,
            isCurrent: true,
          },
        ]
      : []),
    ...session.previousDays.map((day) => ({ ...day, isCurrent: false })),
  ]
}
function details(event: MouseEvent, id: number) {
  if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button !== 0) return
  event.preventDefault()
  void router.push({
    path: `/training-sessions/${id}`,
    state: {
      backTo: route.path,
      backLabel: route.path.startsWith('/pilots/')
        ? 'Back to pilot profile'
        : 'Back to training sessions',
    },
  })
}
</script>
<template>
  <section
    v-if="!isLoading && sessions.length === 0"
    class="w-full rounded-2xl border border-dashed border-line-strong bg-surface p-8 text-center text-sm text-foreground shadow-sm"
  >
    No training sessions found for selected filters.
  </section>
  <section v-else class="w-max max-w-full rounded-2xl border border-line bg-surface shadow-sm">
    <StickyHorizontalScrollArea
      :enable-sticky-scrollbar="sticky"
      :content-scroll-area-class-name="`${sticky ? 'sticky-horizontal-scroll-area' : 'sticky-horizontal-scrollbar'} overflow-x-auto`"
      measure-wrapper-class-name="w-max"
      scrollbar-aria-label="Scroll training sessions horizontally"
    >
      <template v-if="isLoading"
        ><article
          v-for="index in 4"
          :key="index"
          aria-hidden="true"
          class="animate-pulse border-b border-line last:border-b-0"
        >
          <div :class="gridClass">
            <div v-for="cell in 4" :key="cell" class="h-24 rounded-xl bg-surface-muted" />
          </div></article
      ></template>
      <template v-else>
        <article
          v-for="session in sessions"
          :key="session.id"
          class="border-b border-line last:border-b-0"
        >
          <div v-if="roleLabel(session)" class="px-4 pt-3 pb-1">
            <span
              class="inline-flex items-center rounded-full border border-line bg-surface px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.14em] text-foreground"
              >{{ roleLabel(session) }}</span
            >
          </div>
          <div :class="['transition hover:bg-surface-muted', gridClass]">
            <div class="row-span-2 space-y-1">
              <p class="text-xs font-medium text-foreground-secondary">
                {{ formatTrainingSessionTimestamp(session.completedAt) }}
              </p>
              <p class="truncate text-base font-semibold text-foreground" :title="session.title">
                {{ session.title }}
              </p>
              <p class="text-xs text-foreground-secondary">Location</p>
              <AircraftChip
                :color-hex="
                  session.aircraftId !== null
                    ? (aircraftColorsById[session.aircraftId] ?? null)
                    : null
                "
                class="h-8 min-w-[55px] justify-center px-3 py-1.5 text-xs"
                ><span class="truncate">{{
                  session.aircraftId !== null
                    ? (aircraftLabelsById[session.aircraftId] ?? `#${session.aircraftId}`)
                    : '—'
                }}</span></AircraftChip
              >
            </div>
            <CrewMemberCell
              label="Instructor"
              :first-name="session.instructorFirstName"
              :last-name="session.instructorLastName"
              :photo-url="session.instructorPhotoUrl"
            />
            <CrewMemberCell
              label="Crew member 1"
              :first-name="session.cm1FirstName"
              :last-name="session.cm1LastName"
              :photo-url="session.cm1PhotoUrl"
            />
            <CrewMemberCell
              label="Crew member 2"
              :first-name="session.cm2FirstName"
              :last-name="session.cm2LastName"
              :photo-url="session.cm2PhotoUrl"
            />
            <div class="col-[2/5] flex min-w-max flex-nowrap items-center gap-2 self-end">
              <a
                :href="router.resolve(`/training-sessions/${session.id}`).href"
                class="inline-flex h-8 shrink-0 items-center justify-center rounded-full border border-line-strong bg-surface px-3 py-1.5 text-xs font-semibold text-foreground transition hover:border-line-emphasis hover:bg-surface-subtle hover:text-foreground-inverse"
                @click="details($event, session.id)"
                >Details</a
              >
              <RouterLink
                v-for="day in days(session)"
                :key="`${session.id}-${day.id}`"
                :to="`/training-sessions/${day.id}`"
                target="_blank"
                rel="noreferrer"
                :class="[
                  dayClass,
                  day.isCurrent
                    ? 'border-line-emphasis bg-surface-subtle text-foreground-inverse'
                    : 'border-line bg-surface-muted text-foreground',
                ]"
                :title="`Open ${day.title} in a new tab`"
                >{{
                  day.dayIndex !== null && day.dayIndex !== undefined
                    ? `Day ${day.dayIndex}`
                    : day.title
                }}</RouterLink
              >
              <p v-if="days(session).length === 0" class="text-xs text-foreground-secondary">
                Single-day training group
              </p>
            </div>
          </div>
        </article>
      </template>
    </StickyHorizontalScrollArea>
  </section>
</template>
