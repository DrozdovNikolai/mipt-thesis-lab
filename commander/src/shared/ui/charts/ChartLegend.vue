<script setup lang="ts">
defineProps<{ items: { label: string; color: string }[] }>()
</script>
<template>
  <div v-if="items.length" class="flex flex-wrap gap-x-4 gap-y-2">
    <div
      v-for="item in items"
      :key="`${item.label}-${item.color}`"
      class="inline-flex items-center gap-2 text-xs text-foreground-secondary"
    >
      <span
        class="h-[2px] w-6 rounded-full"
        :style="{ backgroundColor: item.color }"
        aria-hidden="true"
      /><span>{{ item.label }}</span>
    </div>
  </div>
</template>
