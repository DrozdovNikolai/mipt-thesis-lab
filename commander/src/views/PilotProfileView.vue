<script setup lang="ts">
import { computed, provide } from 'vue'
import { useRoute } from 'vue-router'
import { useQuery } from '@tanstack/vue-query'
import { commanderApi } from '@/entities/commander/api'
import { commanderKeys } from '@/entities/commander/queryKeys'
import { useSessionStore } from '@/entities/session/store'
import { useSessionScope } from '@/entities/session/useSessionScope'
import { pilotProfileKey } from '@/features/pilot-profile/context'
import PilotAvatar from '@/features/pilots/ui/PilotAvatar.vue'
import AircraftChip from '@/shared/ui/chips/AircraftChip.vue'
import { getErrorMessage } from '@/shared/lib/errorMessage'
const route = useRoute(),
  session = useSessionStore(),
  scope = useSessionScope()
const pilotId = computed(() => String(route.params.pilotId ?? ''))
const pilotQuery = useQuery({
  queryKey: computed(() => [...commanderKeys.root(scope.value), 'pilot', pilotId.value]),
  queryFn: ({ signal }) => commanderApi.getPilotProfile(pilotId.value, signal),
  enabled: computed(() => session.isReady && Boolean(pilotId.value)),
  retry: 0,
})
const aircraftQuery = useQuery({
  queryKey: computed(() => commanderKeys.aircraft(scope.value)),
  queryFn: ({ signal }) => commanderApi.listAircraft(signal),
  enabled: computed(() => session.isReady),
  retry: 0,
})
const pilot = pilotQuery.data
provide(pilotProfileKey, pilot)
const name = computed(() =>
  pilot.value
    ? [pilot.value.firstName?.trim(), pilot.value.lastName?.trim()]
        .filter(Boolean)
        .join(' ')
        .trim() ||
      pilot.value.fullName?.trim() ||
      pilot.value.email
    : '',
)
const initials = computed(() =>
  pilot.value
    ? `${pilot.value.firstName?.trim()[0] ?? ''}${pilot.value.lastName?.trim()[0] ?? ''}`.toUpperCase() ||
      pilot.value.email.slice(0, 2).toUpperCase()
    : '',
)
const colors = computed(() =>
  Object.fromEntries(
    (aircraftQuery.data.value ?? []).map((aircraft) => [aircraft.code, aircraft.colorHex]),
  ),
)
const backClass =
  'inline-flex h-10 items-center justify-center rounded-xl border border-line-strong bg-surface px-4 text-sm font-semibold text-foreground-secondary transition hover:border-line-emphasis hover:bg-surface-subtle hover:text-foreground-inverse'
const tabClass = (active: boolean) =>
  active
    ? 'flex w-full items-center rounded-[14px] border border-line bg-surface px-4 py-3 text-sm font-semibold text-foreground shadow-sm'
    : 'flex w-full items-center rounded-[14px] border border-transparent px-4 py-3 text-sm font-semibold text-foreground-secondary transition hover:border-line hover:bg-surface hover:text-foreground'
</script>
<template>
  <section v-if="!pilotId || pilotQuery.isError.value" class="space-y-4">
    <RouterLink to="/pilots" :class="backClass">Back to pilots</RouterLink>
    <section
      role="alert"
      class="rounded-2xl border border-line-danger bg-danger-soft px-4 py-3 text-sm text-danger"
    >
      {{
        !pilotId
          ? 'Pilot id is missing.'
          : getErrorMessage(pilotQuery.error.value, 'Failed to load pilot profile.')
      }}
    </section>
  </section>
  <section
    v-else-if="!pilot"
    class="grid gap-4 xl:grid-cols-[186px_minmax(0,1fr)]"
    aria-label="Loading pilot profile"
  >
    <div class="h-96 animate-pulse rounded-[28px] bg-surface-muted" />
    <div class="h-64 animate-pulse rounded-[28px] bg-surface-muted" />
  </section>
  <section v-else class="grid gap-4 xl:grid-cols-[186px_minmax(0,1fr)] xl:items-start">
    <aside class="space-y-4 xl:self-start">
      <RouterLink to="/pilots" :class="backClass">Back to pilots</RouterLink>
      <section class="rounded-[28px] border border-line bg-surface p-4 shadow-sm">
        <div class="space-y-5">
          <PilotAvatar
            :photo-url="pilot.photoUrl ?? null"
            :alt="`${name} avatar`"
            :fallback-text="initials"
            class-name="h-[145px] w-[145px] shrink-0 rounded-full border border-line bg-surface-pilot-badge"
            fallback-text-class-name="text-5xl font-semibold text-foreground-pilot-badge"
          />
          <div class="space-y-2 text-center">
            <h1 class="text-xl font-semibold tracking-tight text-foreground">{{ name }}</h1>
          </div>
          <dl class="space-y-3">
            <div class="rounded-2xl border border-line bg-surface-muted px-4 py-3">
              <dt class="text-[11px] font-semibold uppercase tracking-[0.16em] text-foreground">
                Position
              </dt>
              <dd class="mt-2 text-sm font-semibold text-foreground">
                {{ pilot.position?.trim() || 'Not set' }}
              </dd>
            </div>
            <div class="rounded-2xl border border-line bg-surface-muted px-4 py-3">
              <dt class="text-[11px] font-semibold uppercase tracking-[0.16em] text-foreground">
                Aircraft
              </dt>
              <dd class="mt-3 flex flex-wrap gap-2">
                <AircraftChip
                  v-for="code in pilot.aircraftCodes"
                  :key="code"
                  :color-hex="colors[code]"
                  class="px-2.5 py-1 text-xs"
                  >{{ code }}</AircraftChip
                ><span
                  v-if="!pilot.aircraftCodes.length"
                  class="text-sm font-semibold text-foreground"
                  >No aircraft assigned</span
                >
              </dd>
            </div>
          </dl>
        </div>
      </section>
      <nav class="rounded-[28px] border border-line bg-surface p-2 shadow-sm">
        <div class="space-y-2">
          <RouterLink
            v-for="tab in [
              { path: 'training-data', label: 'Training data' },
              { path: 'profile', label: 'Profile' },
            ]"
            :key="tab.path"
            :to="`/pilots/${encodeURIComponent(pilotId)}/${tab.path}`"
            :class="tabClass(route.path.endsWith(`/${tab.path}`))"
            >{{ tab.label }}</RouterLink
          >
        </div>
      </nav>
    </aside>
    <div class="min-w-0"><RouterView :key="pilotId" /></div>
  </section>
</template>
