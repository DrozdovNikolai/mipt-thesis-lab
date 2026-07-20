<script setup lang="ts">
import type { TrainingSessionDetailAssessment } from '@/entities/commander/types'
defineProps<{ assessment: TrainingSessionDetailAssessment | null }>()
</script>
<template>
  <section
    class="space-y-4 rounded-[28px] border border-line bg-surface p-5 shadow-sm"
    :class="{ 'border-dashed border-line-strong': !assessment }"
  >
    <header class="space-y-1">
      <h2 class="text-lg font-semibold text-foreground">AI review</h2>
      <p class="text-sm text-foreground-secondary">
        {{
          assessment
            ? 'AI-generated observations for the selected crew assessment.'
            : 'Choose a crew assessment to inspect AI review content.'
        }}
      </p>
    </header>
    <template v-if="assessment">
      <div v-if="assessment.aiReviews.length > 0" class="space-y-3">
        <article
          v-for="review in assessment.aiReviews"
          :key="review.id"
          class="rounded-2xl border border-line bg-surface-muted px-4 py-4"
        >
          <div class="flex flex-wrap items-center gap-2">
            <span
              class="inline-flex items-center rounded-full border border-line bg-surface px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.14em] text-foreground"
              >{{ review.competenceCode ?? 'Overall' }}</span
            ><span v-if="review.competenceName" class="text-sm text-foreground-secondary">{{
              review.competenceName
            }}</span>
          </div>
          <p class="mt-3 text-sm leading-6 text-foreground">{{ review.text }}</p>
        </article>
      </div>
      <div
        v-else
        class="rounded-2xl border border-dashed border-line-strong px-4 py-6 text-sm text-foreground-secondary"
      >
        No AI review content is available for this assessment.
      </div>
    </template>
  </section>
</template>
