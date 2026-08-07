<script setup lang="ts">
import { computed } from 'vue'
const props = withDefaults(
  defineProps<{
    title: string
    description?: string
    meta?: string
    skeletonVariant?: 'vertical-bars' | 'horizontal-bars' | 'line'
    isLoading?: boolean
    isRefreshing?: boolean
    errorMessage?: string | null
    hasContent: boolean
    emptyMessage: string
  }>(),
  { skeletonVariant: 'vertical-bars' },
)
const initialLoading = computed(() => props.isLoading && !props.hasContent)
</script>
<template>
  <section
    class="flex min-w-0 flex-col rounded-[28px] border border-line bg-surface px-2 pt-2 pb-1.5 shadow-sm lg:px-2.5 lg:pt-2.5 lg:pb-2"
  >
    <header class="mb-3 flex flex-col gap-2.5 md:flex-row md:items-start md:justify-between">
      <div class="space-y-1">
        <h2 class="text-lg font-semibold tracking-tight text-foreground">{{ title }}</h2>
        <p v-if="description" class="text-sm text-foreground-inverse">{{ description }}</p>
      </div>
      <div class="flex flex-wrap items-center gap-2">
        <span
          v-if="meta"
          class="inline-flex h-8 items-center rounded-full bg-surface-subtle px-3 text-xs font-semibold text-foreground-inverse"
          >{{ meta }}</span
        ><span
          v-if="isRefreshing && !initialLoading"
          class="inline-flex h-8 items-center rounded-full bg-warning-soft px-3 text-xs font-semibold text-warning"
          >Updating...</span
        >
      </div>
    </header>
    <div v-if="$slots.controls" class="mb-3"><slot name="controls" /></div>
    <div v-if="initialLoading" class="flex flex-1 flex-col" aria-hidden="true">
      <div
        v-if="skeletonVariant === 'horizontal-bars'"
        class="flex h-full min-h-[220px] flex-col justify-around gap-3 rounded-2xl bg-surface-muted p-4"
      >
        <div v-for="index in 5" :key="index" class="flex items-center gap-3">
          <div class="h-3 w-20 animate-pulse rounded bg-surface-subtle" />
          <div
            class="h-5 animate-pulse rounded-full bg-surface-subtle"
            :style="{ width: `${36 + (((index - 1) * 13) % 48)}%` }"
          />
        </div>
      </div>
      <div
        v-else-if="skeletonVariant === 'line'"
        class="h-full min-h-[320px] animate-pulse rounded-2xl bg-surface-muted"
      />
      <div
        v-else
        class="grid h-full min-h-[220px] grid-cols-6 items-end gap-3 rounded-2xl bg-surface-muted p-4"
      >
        <div
          v-for="index in 12"
          :key="index"
          class="animate-pulse rounded-t-xl bg-surface-subtle"
          :style="{ height: `${28 + (((index - 1) * 19) % 160)}px` }"
        />
      </div>
    </div>
    <div
      v-else-if="!hasContent && errorMessage"
      role="alert"
      class="rounded-2xl border border-line-danger bg-danger-soft px-4 py-3 text-sm text-danger"
    >
      {{ errorMessage }}
    </div>
    <div
      v-else-if="!hasContent"
      class="rounded-2xl border border-dashed border-line-strong bg-surface-muted px-5 py-10 text-center text-sm text-foreground-inverse"
    >
      {{ emptyMessage }}
    </div>
    <div v-else class="flex min-h-0 flex-1 flex-col gap-3">
      <div
        v-if="errorMessage"
        class="rounded-2xl border border-line-warning bg-warning-soft px-4 py-3 text-sm text-warning"
      >
        {{ errorMessage }}
      </div>
      <slot />
    </div>
  </section>
</template>
