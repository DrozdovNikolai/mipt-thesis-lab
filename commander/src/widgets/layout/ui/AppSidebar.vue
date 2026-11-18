<script setup lang="ts">
import { RouterLink, useRoute } from 'vue-router'
import BrandLogo from '@/shared/branding/BrandLogo.vue'

defineProps<{ items: readonly { label: string; to: string; end?: boolean }[] }>()
const route = useRoute()
const active = (item: { to: string; end?: boolean }) =>
  route.path === item.to || (!item.end && route.path.startsWith(`${item.to}/`))
</script>

<template>
  <aside
    class="flex w-full shrink-0 flex-col border-b border-chrome-line bg-chrome p-4 md:h-full md:w-64 md:self-stretch md:overflow-y-auto md:border-b-0 md:border-r"
  >
    <div class="mb-6 flex min-h-11 items-center px-1">
      <BrandLogo class="sidebar-brand-logo" />
    </div>
    <nav class="flex flex-col gap-1">
      <RouterLink
        v-for="item in items"
        :key="item.to"
        :to="item.to"
        :aria-current="active(item) ? 'page' : undefined"
        :class="
          active(item)
            ? 'relative flex h-10 items-center rounded-xl px-3 pl-5 text-sm font-medium text-chrome-fg'
            : 'relative flex h-10 items-center rounded-xl px-3 pl-5 text-sm font-medium text-chrome-fg-muted transition hover:bg-chrome-elevated hover:text-chrome-fg'
        "
      >
        <span
          v-if="active(item)"
          class="absolute left-0 top-0 h-full w-1 rounded-full bg-chrome-accent"
          aria-hidden="true"
        />
        <span>{{ item.label }}</span>
      </RouterLink>
    </nav>
  </aside>
</template>
