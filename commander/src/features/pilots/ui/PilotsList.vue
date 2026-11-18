<script setup lang="ts">
import type { SessionUser } from '@/entities/session/types'
import PilotAvatar from './PilotAvatar.vue'
import PilotRatingBadge from './PilotRatingBadge.vue'
import AircraftChip from '@/shared/ui/chips/AircraftChip.vue'
import StickyHorizontalScrollArea from '@/shared/ui/lists/StickyHorizontalScrollArea.vue'

defineProps<{
  pilots: readonly SessionUser[]
  aircraftColorsByCode: Record<string, string>
  isLoading: boolean
}>()
function getPilotName(pilot: SessionUser) {
  const first = pilot.firstName?.trim() ?? ''
  const last = pilot.lastName?.trim() ?? ''
  return last && first ? `${last}, ${first}` : last || first || pilot.login
}
function getInitials(pilot: SessionUser) {
  return (
    `${pilot.firstName?.trim()[0] ?? ''}${pilot.lastName?.trim()[0] ?? ''}`.toUpperCase() ||
    pilot.login.slice(0, 2).toUpperCase()
  )
}
function openProfile(id: string) {
  window.open(`/pilots/${encodeURIComponent(id)}`, '_blank', 'noopener,noreferrer')
}
function onKey(event: KeyboardEvent, id: string) {
  if (event.key === 'Enter' || event.key === ' ') {
    event.preventDefault()
    openProfile(id)
  }
}
</script>
<template>
  <section
    v-if="!isLoading && pilots.length === 0"
    class="w-full rounded-2xl border border-dashed border-line-strong bg-surface p-8 text-center text-sm text-foreground shadow-sm"
  >
    No pilots found for selected filters.
  </section>
  <section v-else class="w-max max-w-full rounded-2xl border border-line bg-surface shadow-sm">
    <StickyHorizontalScrollArea
      enable-sticky-scrollbar
      content-scroll-area-class-name="sticky-horizontal-scroll-area overflow-x-auto"
      measure-wrapper-class-name="w-max"
      scrollbar-aria-label="Scroll pilots horizontally"
    >
      <table class="w-[940px] table-fixed">
        <caption class="sr-only">
          Pilots directory
        </caption>
        <colgroup>
          <col class="w-[240px]" />
          <col class="w-[340px]" />
          <col class="w-[240px]" />
          <col class="w-[120px]" />
        </colgroup>
        <thead class="sr-only">
          <tr>
            <th scope="col">Pilot</th>
            <th scope="col">Position and aircraft</th>
            <th scope="col">Email</th>
            <th scope="col">Rating</th>
          </tr>
        </thead>
        <tbody v-if="isLoading">
          <tr
            v-for="index in 6"
            :key="index"
            class="animate-pulse border-b border-line last:border-b-0"
            aria-hidden="true"
          >
            <td class="px-3 py-3 align-middle">
              <div class="flex items-center gap-2.5">
                <div class="h-11 w-11 rounded-full bg-surface-pilot-badge" />
                <div class="min-w-0 max-w-[160px] flex-1 space-y-2">
                  <div class="h-3 w-2/3 rounded bg-surface-subtle" />
                  <div class="h-3 w-1/3 rounded bg-surface-subtle" />
                </div>
              </div>
            </td>
            <td class="px-3 py-3 align-middle">
              <div class="flex flex-wrap gap-2">
                <div class="h-8 w-24 rounded-full bg-surface-muted" />
                <div class="h-8 w-20 rounded-full bg-surface-muted" />
                <div class="h-8 w-20 rounded-full bg-surface-muted" />
              </div>
            </td>
            <td class="px-3 py-3 align-middle">
              <div class="space-y-2">
                <div class="h-3 w-3/4 rounded bg-surface-subtle" />
                <div class="h-3 w-1/2 rounded bg-surface-subtle" />
              </div>
            </td>
            <td class="px-3 py-3 align-middle">
              <div class="flex justify-end">
                <div class="h-9 w-9 rounded-full bg-surface-pilot-badge" />
              </div>
            </td>
          </tr>
        </tbody>
        <tbody v-else>
          <tr
            v-for="pilot in pilots"
            :key="pilot.id"
            tabindex="0"
            role="link"
            :aria-label="`Open ${getPilotName(pilot)} profile in a new tab`"
            class="cursor-pointer border-b border-line transition hover:bg-surface-muted focus-visible:bg-surface-muted focus-visible:outline-none last:border-b-0"
            @click="openProfile(pilot.id)"
            @keydown="onKey($event, pilot.id)"
          >
            <td class="px-3 py-3 align-middle">
              <div class="flex min-w-0 items-center gap-2.5">
                <PilotAvatar
                  :photo-url="pilot.photoUrl"
                  :alt="`${getPilotName(pilot)} avatar`"
                  :fallback-text="getInitials(pilot)"
                />
                <div class="min-w-0 flex-1 space-y-0.5 text-foreground">
                  <p
                    class="truncate text-[13px] leading-tight font-semibold"
                    :title="getPilotName(pilot)"
                  >
                    {{ getPilotName(pilot) }}
                  </p>
                </div>
              </div>
            </td>
            <td class="px-3 py-3 align-middle">
              <div class="flex flex-wrap gap-2">
                <span
                  v-if="pilot.position"
                  class="inline-flex items-center rounded-full border border-line bg-surface-muted px-3 py-1.5 text-xs font-semibold text-foreground"
                  :title="pilot.position"
                  >{{ pilot.position }}</span
                ><template v-if="pilot.aircraftCodes.length"
                  ><AircraftChip
                    v-for="code in pilot.aircraftCodes"
                    :key="code"
                    :color-hex="aircraftColorsByCode[code]"
                    class="px-3 py-1.5 text-xs"
                    :title="code"
                    >{{ code }}</AircraftChip
                  ></template
                ><span v-else class="text-sm text-foreground-secondary">No aircraft assigned</span>
              </div>
            </td>
            <td class="px-3 py-3 align-middle">
              <p class="truncate text-sm text-foreground" :title="pilot.email || undefined">
                {{ pilot.email || 'Not set' }}
              </p>
            </td>
            <td class="px-3 py-3 align-middle">
              <div class="flex justify-end"><PilotRatingBadge :rating="pilot.rating" /></div>
            </td>
          </tr>
        </tbody>
      </table>
    </StickyHorizontalScrollArea>
  </section>
</template>
