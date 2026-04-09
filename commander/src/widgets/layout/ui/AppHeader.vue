<script setup lang="ts">
defineProps<{ userLabel: string }>()
defineEmits<{ logout: [] }>()
</script>

<template>
  <header
    class="z-20 flex h-16 shrink-0 items-center justify-between border-b border-chrome-line bg-chrome px-4"
  >
    <div>
      <p class="text-sm font-semibold text-chrome-fg">{{ userLabel }}</p>
    </div>
    <button
      type="button"
      class="inline-flex h-9 items-center rounded-lg border border-chrome-line-strong bg-chrome-elevated px-3 text-sm font-medium text-chrome-fg transition hover:bg-chrome-hover"
      @click="$emit('logout')"
    >
      Logout
    </button>
  </header>
</template>
