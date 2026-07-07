<script setup lang="ts">
import { computed } from 'vue'
import type {
  TrainingSessionDetailLatestCrewSwap,
  TrainingSessionDetailModule,
  TrainingSessionDetailParticipant,
  TrainingSessionProjectionSource,
} from '@/entities/commander/types'
import { formatTrainingDurationMs } from '../lib/crewTimelinePresentation'
import {
  getParticipantName,
  getMappingLabel,
  getLatestSwapContext,
  formatAcceptedAt,
} from '../lib/crewSummary'
const props = defineProps<{
  participants: TrainingSessionDetailParticipant[]
  modules: TrainingSessionDetailModule[]
  projectionSource: TrainingSessionProjectionSource
  latestSwap: TrainingSessionDetailLatestCrewSwap | null
  latestSwapProjectionAvailable: boolean
}>()
const mapping = computed(() => {
  const cm1 = props.participants.find((p) => p.finalCrewSlot === 'CM1'),
    cm2 = props.participants.find((p) => p.finalCrewSlot === 'CM2')
  return cm1 && cm2
    ? getMappingLabel(props.participants, cm1.assessmentId, cm2.assessmentId)
    : 'Current assignment unavailable'
})
const description = computed(() =>
  props.projectionSource === 'LEGACY_PLANNED'
    ? 'Legacy planned roles: this session was completed without a live crew timeline.'
    : !props.latestSwapProjectionAvailable
      ? 'Current mapping comes from the sealed final state. Latest-swap details require the compatible backend contract.'
      : props.projectionSource === 'ACTUAL_TIMELINE' && props.latestSwap
        ? 'The current mapping comes from the sealed latest accepted swap. PF/PM totals use the complete server-side history.'
        : props.projectionSource === 'ACTUAL_TIMELINE'
          ? 'No swaps were accepted; the sealed current mapping equals the initial assignment. PF/PM totals use the complete server-side timeline.'
          : 'Legacy planned roles: this session was completed without a live crew timeline.',
)
</script>
<template>
  <section class="mt-5 border-t border-line pt-5" aria-labelledby="crew-runtime-heading">
    <div class="flex flex-wrap items-start justify-between gap-3">
      <div>
        <h2 id="crew-runtime-heading" class="text-base font-semibold text-foreground">
          Current crew assignment
        </h2>
        <p class="mt-1 text-xs text-foreground-secondary">{{ description }}</p>
      </div>
      <span
        class="inline-flex rounded-full border border-line-strong bg-surface-muted px-3 py-1 text-xs font-semibold text-foreground"
        >{{
          !latestSwapProjectionAvailable
            ? 'Latest swap unavailable'
            : latestSwap
              ? `Latest accepted · revision ${latestSwap.serverRevision}`
              : 'No accepted swaps'
        }}</span
      >
    </div>
    <template v-if="latestSwap">
      <p class="mt-3 text-xs text-foreground-secondary">
        {{ getLatestSwapContext(latestSwap, modules) }} ·
        {{ formatAcceptedAt(latestSwap.acceptedAt) }}
      </p>
      <dl class="mt-4 grid gap-3 xl:grid-cols-2">
        <div class="rounded-2xl border border-line bg-surface-muted px-4 py-3">
          <dt class="text-[11px] font-semibold uppercase tracking-wide text-foreground-secondary">
            Before latest swap
          </dt>
          <dd class="mt-1 text-sm font-semibold text-foreground">
            {{
              getMappingLabel(
                participants,
                latestSwap.cm1AssessmentIdBefore,
                latestSwap.cm2AssessmentIdBefore,
              )
            }}
          </dd>
        </div>
        <div class="rounded-2xl border border-line-emphasis bg-surface-muted px-4 py-3">
          <dt class="text-[11px] font-semibold uppercase tracking-wide text-foreground-secondary">
            Current assignment
          </dt>
          <dd class="mt-1 text-sm font-semibold text-foreground">
            {{
              getMappingLabel(
                participants,
                latestSwap.cm1AssessmentIdAfter,
                latestSwap.cm2AssessmentIdAfter,
              )
            }}
          </dd>
        </div>
      </dl>
    </template>
    <dl v-else class="mt-4">
      <div class="rounded-2xl border border-line-emphasis bg-surface-muted px-4 py-3">
        <dt class="text-[11px] font-semibold uppercase tracking-wide text-foreground-secondary">
          Current assignment
        </dt>
        <dd class="mt-1 text-sm font-semibold text-foreground">{{ mapping }}</dd>
      </div>
    </dl>
    <ul class="mt-3 grid gap-3 xl:grid-cols-2" aria-label="Participant PF and PM duration totals">
      <li
        v-for="participant in participants"
        :key="participant.assessmentId"
        class="rounded-2xl border border-line bg-surface px-4 py-3"
      >
        <p class="text-sm font-semibold text-foreground">{{ getParticipantName(participant) }}</p>
        <p class="mt-1 text-xs text-foreground-secondary">
          Current at completion · {{ participant.finalCrewSlot }}
        </p>
        <div class="mt-3 flex flex-wrap gap-2 text-xs font-semibold">
          <span
            class="rounded-full border border-[#284692]/30 bg-[#284692]/10 px-2.5 py-1 text-[#284692]"
            >PF {{ formatTrainingDurationMs(participant.pfDurationMs) }}</span
          ><span
            class="rounded-full border border-[#1D9634]/30 bg-[#1D9634]/10 px-2.5 py-1 text-[#1D7A31]"
            >PM {{ formatTrainingDurationMs(participant.pmDurationMs) }}</span
          >
        </div>
      </li>
    </ul>
  </section>
</template>
