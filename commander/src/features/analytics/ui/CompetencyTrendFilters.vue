<script setup lang="ts">
const id = defineModel<number | null>('competenceId', { required: true })
defineProps<{ competenceOptions: { id: number; label: string }[] }>()
</script>
<template>
  <label class="flex flex-wrap items-center gap-3 rounded-2xl border border-line bg-surface p-3"
    ><span class="shrink-0 text-xs font-semibold uppercase tracking-wide text-foreground"
      >Competency</span
    ><select
      v-model="id"
      :disabled="!competenceOptions.length"
      class="h-9 w-full flex-1 basis-36 min-w-0 max-w-[360px] rounded-xl border border-line bg-surface px-3 text-sm text-foreground outline-none transition focus:border-line-emphasis focus:ring-2 focus:ring-focus"
    >
      <option v-if="!competenceOptions.length" :value="null">No competencies</option>
      <option v-for="option in competenceOptions" :key="option.id" :value="option.id">
        {{ option.label }}
      </option>
    </select></label
  >
</template>
