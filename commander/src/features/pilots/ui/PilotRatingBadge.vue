<script setup lang="ts">
import { computed } from 'vue'
const props = defineProps<{ rating?: string | null }>()
const displayRating = computed(() => {
  const value = props.rating?.trim()
  if (!value) return '-'
  const numeric = Number(value)
  return Number.isFinite(numeric) ? numeric.toFixed(1).replace(/\.0$/, '') : value
})
</script>
<template>
  <div
    class="flex h-9 w-9 shrink-0 items-center justify-center rounded-full border border-line bg-surface-pilot-badge text-[11px] font-semibold text-foreground-pilot-badge"
    :aria-label="rating ? `Pilot rating ${displayRating}` : 'Pilot rating unavailable'"
    :title="rating ? `Rating ${displayRating}` : 'Rating unavailable'"
  >
    {{ displayRating }}
  </div>
</template>
