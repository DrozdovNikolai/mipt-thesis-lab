<script setup lang="ts">
import PilotAvatar from '@/features/pilots/ui/PilotAvatar.vue'
import { getPersonLabel } from '../lib/trainingSessionPresentation'
defineProps<{
  label: string
  firstName: string | null
  lastName: string | null
  photoUrl?: string | null
}>()
function initials(first: string | null, last: string | null) {
  return `${first?.trim()[0] ?? ''}${last?.trim()[0] ?? ''}`.toUpperCase() || 'UN'
}
</script>
<template>
  <div class="flex items-start gap-3">
    <PilotAvatar
      :photo-url="photoUrl ?? null"
      :alt="`${getPersonLabel(firstName, lastName, 'Unassigned')} avatar`"
      :fallback-text="initials(firstName, lastName)"
    />
    <div class="min-w-0 space-y-1">
      <p class="text-[11px] font-medium text-foreground-secondary">{{ label }}</p>
      <p
        class="truncate text-sm font-semibold text-foreground"
        :title="getPersonLabel(firstName, lastName, 'Unassigned')"
      >
        {{ getPersonLabel(firstName, lastName, 'Unassigned') }}
      </p>
    </div>
  </div>
</template>
