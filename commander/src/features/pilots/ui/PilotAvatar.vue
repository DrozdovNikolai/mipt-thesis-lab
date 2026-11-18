<script setup lang="ts">
import { computed } from 'vue'
import { useQuery } from '@tanstack/vue-query'
import { useSessionStore } from '@/entities/session/store'
import { api } from '@/shared/api/api'
import { ApiError } from '@/shared/api/requestExecutor'
import { resolveMediaRequestPath } from '@/shared/lib/media/resolveMediaRequestPath'
import { useObjectUrl } from '@/shared/lib/media/useObjectUrl'

const props = defineProps<{
  photoUrl: string | null
  alt: string
  fallbackText: string
  className?: string
  fallbackTextClassName?: string
}>()
const session = useSessionStore()
const mediaPath = computed(() => (props.photoUrl ? resolveMediaRequestPath(props.photoUrl) : null))
const containerClass = computed(
  () =>
    props.className ?? 'h-11 w-11 shrink-0 rounded-full border border-line bg-surface-pilot-badge',
)
const { data, isPending } = useQuery({
  queryKey: computed(() => [
    'media',
    session.user?.id,
    session.user?.airlineId,
    'photo',
    mediaPath.value,
  ]),
  queryFn: async ({ signal }) => {
    if (!mediaPath.value) throw new Error('Missing media path')
    try {
      return await api.getBlob(mediaPath.value, { signal })
    } catch (error) {
      if (error instanceof ApiError && error.status === 404) return null
      throw error
    }
  },
  enabled: computed(() => Boolean(mediaPath.value) && session.isReady),
  staleTime: 5 * 60 * 1000,
  gcTime: 30 * 60 * 1000,
  retry: (count, error) =>
    error instanceof ApiError && error.status >= 400 && error.status < 500 ? false : count < 2,
  retryOnMount: false,
})
const objectUrl = useObjectUrl(data)
</script>
<template>
  <img
    v-if="objectUrl"
    :src="objectUrl"
    :alt="alt"
    :class="[containerClass, 'object-cover']"
    loading="lazy"
  />
  <div v-else-if="isPending && mediaPath" :class="[containerClass, 'animate-pulse']" />
  <div
    v-else
    :class="[
      'flex items-center justify-center',
      containerClass,
      fallbackTextClassName ?? 'text-xs font-semibold text-foreground-pilot-badge',
    ]"
  >
    {{ fallbackText }}
  </div>
</template>
