<script setup lang="ts">
const top = defineModel<number | null>('topPerformersCount', { required: true })
const concern = defineModel<number | null>('trainingConcernCount', { required: true })
defineProps<{ maxPilotCount: number }>()
function parse(event: Event) {
  const value = (event.target as HTMLInputElement).value
  const n = Number(value)
  return value && Number.isFinite(n) && n > 0 ? Math.floor(n) : null
}
const fieldClass =
  'h-9 min-w-0 flex-1 rounded-xl border border-line bg-surface px-2 text-right text-sm text-foreground outline-none transition focus:border-line-emphasis focus:ring-2 focus:ring-focus'
</script>
<template>
  <section
    class="grid gap-2 rounded-2xl border border-line bg-surface p-3 grid-cols-[repeat(auto-fit,minmax(min(100%,180px),1fr))]"
  >
    <label class="flex min-w-0 w-full items-center gap-1.5"
      ><span class="shrink-0 whitespace-nowrap text-xs font-semibold tracking-wide text-foreground"
        >Top performers</span
      ><input
        type="number"
        inputmode="numeric"
        :min="0"
        :max="Math.max(maxPilotCount, 0)"
        :step="1"
        :value="top ?? ''"
        :class="fieldClass"
        @input="top = parse($event)" /></label
    ><label class="flex min-w-0 w-full items-center gap-1.5"
      ><span class="shrink-0 whitespace-nowrap text-xs font-semibold tracking-wide text-foreground"
        >Training concern</span
      ><input
        type="number"
        inputmode="numeric"
        :min="0"
        :max="Math.max(maxPilotCount, 0)"
        :step="1"
        :value="concern ?? ''"
        :class="fieldClass"
        @input="concern = parse($event)"
    /></label>
  </section>
</template>
