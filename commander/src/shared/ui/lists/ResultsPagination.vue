<script setup lang="ts">
defineProps<{ total: number; limit: number; offset: number }>()
defineEmits<{ previous: []; next: [] }>()
const buttonClassName =
  'inline-flex h-9 items-center rounded-lg border border-line-strong bg-surface px-3 text-sm font-medium text-foreground-secondary transition hover:bg-surface-muted disabled:cursor-not-allowed disabled:opacity-50'
</script>
<template>
  <section
    class="flex w-full flex-wrap items-center justify-between gap-3 rounded-2xl border border-line bg-surface px-4 py-3 shadow-sm"
  >
    <p class="text-sm text-foreground">
      Showing <span class="font-semibold text-foreground">{{ total === 0 ? 0 : offset + 1 }}</span
      >-<span class="font-semibold text-foreground">{{ Math.min(offset + limit, total) }}</span> of
      <span class="font-semibold text-foreground">{{ total }}</span>
    </p>
    <div class="flex items-center gap-2">
      <button
        type="button"
        :class="buttonClassName"
        :disabled="offset <= 0"
        @click="$emit('previous')"
      >
        Previous
      </button>
      <button
        type="button"
        :class="buttonClassName"
        :disabled="offset + limit >= total"
        @click="$emit('next')"
      >
        Next
      </button>
    </div>
  </section>
</template>
