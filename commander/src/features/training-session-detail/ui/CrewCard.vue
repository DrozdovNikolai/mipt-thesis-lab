<script setup lang="ts">
import { computed } from 'vue'
import PilotAvatar from '@/features/pilots/ui/PilotAvatar.vue'
import { getPersonLabel } from '@/features/training-sessions/lib/trainingSessionPresentation'
const props = defineProps<{
  label: string
  firstName: string | null
  lastName: string | null
  fallback: string
  photoUrl?: string | null
  isActive?: boolean
  isDisabled?: boolean
}>()
const emit = defineEmits<{ select: [] }>()
const name = computed(() => getPersonLabel(props.firstName, props.lastName, props.fallback))
const initials = computed(
  () =>
    `${props.firstName?.trim()[0] ?? ''}${props.lastName?.trim()[0] ?? ''}`.toUpperCase() ||
    props.fallback.slice(0, 2).toUpperCase(),
)
</script>
<template>
  <button
    type="button"
    :disabled="isDisabled"
    :class="[
      'group rounded-2xl px-3 py-3 text-left transition',
      isActive ? 'bg-surface-subtle' : 'bg-transparent',
      isDisabled ? 'cursor-default' : 'cursor-pointer hover:bg-surface-subtle',
    ]"
    @click="emit('select')"
  >
    <div class="flex items-start gap-3">
      <PilotAvatar
        :photo-url="photoUrl ?? null"
        :alt="`${name} avatar`"
        :fallback-text="initials"
      />
      <div class="min-w-0 space-y-1">
        <p
          :class="[
            'text-[11px] font-medium',
            isActive ? 'text-foreground-inverse' : 'text-foreground-secondary',
            !isDisabled && !isActive && 'transition group-hover:text-foreground-inverse',
          ]"
        >
          {{ label }}
        </p>
        <p
          :title="name"
          :class="[
            'truncate text-sm font-semibold',
            isActive ? 'text-foreground-inverse' : 'text-foreground',
            !isDisabled && !isActive && 'transition group-hover:text-foreground-inverse',
          ]"
        >
          {{ name }}
        </p>
      </div>
    </div>
  </button>
</template>
