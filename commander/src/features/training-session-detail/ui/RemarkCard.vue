<script setup lang="ts">
import { computed } from 'vue'
import type {
  TrainingSessionDetailAssessmentRemark,
  TrainingSessionProjectionSource,
} from '@/entities/commander/types'
import {
  dutyPresentation,
  formatRemarkHashtag,
  getRemarkMetadataColor,
  getRemarkOffsetMs,
} from '../lib/dayPlan'
import { formatTrainingDurationMs } from '../lib/crewTimelinePresentation'
const props = defineProps<{
  remark: TrainingSessionDetailAssessmentRemark
  projectionSource: TrainingSessionProjectionSource
}>()
const legacy = computed(() => {
  const source = props.remark.roleProjectionSource ?? props.remark.timelineSource
  return source === 'LEGACY_STATIC' || (!source && props.projectionSource === 'LEGACY_PLANNED')
})
</script>
<template>
  <article class="rounded-xl border border-line bg-surface px-3 py-3">
    <div
      class="flex flex-wrap items-center gap-2 text-[11px] font-semibold text-foreground-secondary"
    >
      <span>{{ formatTrainingDurationMs(getRemarkOffsetMs(remark)) }}</span
      ><span>·</span
      ><span>{{
        legacy ? 'Legacy planned role' : dutyPresentation[remark.dutyAtObservation ?? 'NONE'].label
      }}</span
      ><span v-if="remark.crewSlotAtObservation"
        >· {{ remark.crewSlotAtObservation }} at observation</span
      >
    </div>
    <p
      v-if="
        remark.competenceCode || remark.behaviouralIndicatorCode || remark.behaviouralIndicatorName
      "
      class="mt-2 text-xs font-medium text-foreground-secondary"
    >
      <span
        v-if="remark.competenceCode"
        class="font-semibold"
        :style="{ color: getRemarkMetadataColor(remark.isPositive) }"
        >{{ remark.competenceCode }}</span
      ><template v-if="remark.behaviouralIndicatorCode"
        >{{ remark.competenceCode ? ' • ' : ''
        }}<span>{{ remark.behaviouralIndicatorCode }}</span></template
      ><template v-if="remark.behaviouralIndicatorName"
        >{{ remark.competenceCode || remark.behaviouralIndicatorCode ? ' • ' : ''
        }}<span>{{ remark.behaviouralIndicatorName }}</span></template
      >
    </p>
    <span
      v-if="formatRemarkHashtag(remark.hashtag)"
      class="mt-2 inline-flex items-center rounded-full border border-line bg-surface-muted px-2 py-0.5 text-[11px] font-semibold text-foreground-secondary"
      >{{ formatRemarkHashtag(remark.hashtag) }}</span
    >
    <p class="mt-3 text-sm leading-6 text-foreground">
      {{ remark.comment?.trim() || 'No remark comment was provided.' }}
    </p>
  </article>
</template>
