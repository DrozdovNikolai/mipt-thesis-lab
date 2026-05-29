<script setup lang="ts">
import { computed } from 'vue'
import { useQuery } from '@tanstack/vue-query'
import { usePilotProfile } from '@/features/pilot-profile/context'
import { commanderApi } from '@/entities/commander/api'
import { commanderKeys } from '@/entities/commander/queryKeys'
import { useSessionScope } from '@/entities/session/useSessionScope'
import AircraftChip from '@/shared/ui/chips/AircraftChip.vue'
const pilot = usePilotProfile(),
  scope = useSessionScope()
const aircraft = useQuery({
  queryKey: computed(() => commanderKeys.aircraft(scope.value)),
  queryFn: ({ signal }) => commanderApi.listAircraft(signal),
  retry: 0,
})
const colors = computed(() =>
  Object.fromEntries((aircraft.data.value ?? []).map((item) => [item.code, item.colorHex])),
)
const value = (text: string | null | undefined) => text?.trim() || 'Not provided'
const fields = computed(() =>
  pilot.value
    ? [
        { name: 'Full name', value: value(pilot.value.fullName) },
        { name: 'Email', value: pilot.value.email },
        { name: 'Phone', value: value(pilot.value.phone) },
        { name: 'Position', value: value(pilot.value.position) },
        { name: 'Rating', value: pilot.value.rating ?? '—' },
        { name: 'Aircraft count', value: pilot.value.aircraftCodes.length },
      ]
    : [],
)
</script>
<template>
  <section v-if="pilot" class="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(280px,340px)]">
    <section class="rounded-[28px] border border-line bg-surface p-5 shadow-sm">
      <header class="space-y-1">
        <h2 class="text-lg font-semibold text-foreground">General information</h2>
        <p class="text-sm text-foreground-secondary">
          Primary profile data from the commander pilots endpoint.
        </p>
      </header>
      <dl class="mt-5 grid gap-4 sm:grid-cols-2">
        <div
          v-for="field in fields"
          :key="field.name"
          class="rounded-2xl border border-line bg-surface-muted px-4 py-3"
        >
          <dt class="text-[11px] font-semibold uppercase tracking-[0.16em] text-foreground">
            {{ field.name }}
          </dt>
          <dd
            :class="[
              'mt-2 text-sm font-medium text-foreground',
              field.name === 'Email' && 'break-all',
            ]"
          >
            {{ field.value }}
          </dd>
        </div>
      </dl>
    </section>
    <aside class="space-y-4">
      <section class="rounded-[28px] border border-line bg-surface p-5 shadow-sm">
        <header class="space-y-1">
          <h2 class="text-lg font-semibold text-foreground">Assigned aircraft</h2>
          <p class="text-sm text-foreground-secondary">Aircraft codes linked to this pilot.</p>
        </header>
        <div v-if="pilot.aircraftCodes.length" class="mt-5 flex flex-wrap gap-2">
          <AircraftChip
            v-for="code in pilot.aircraftCodes"
            :key="code"
            :color-hex="colors[code]"
            class="px-3 py-1.5 text-xs"
            >{{ code }}</AircraftChip
          >
        </div>
        <p v-else class="mt-5 text-sm text-foreground-secondary">
          No aircraft assigned to this pilot.
        </p>
      </section>
      <section class="rounded-[28px] border border-line bg-surface p-5 shadow-sm">
        <header class="space-y-1">
          <h2 class="text-lg font-semibold text-foreground">Identifiers</h2>
          <p class="text-sm text-foreground-secondary">
            Technical identifiers from the profile payload.
          </p>
        </header>
        <dl class="mt-5 space-y-3 text-sm">
          <div>
            <dt class="text-[11px] font-semibold uppercase tracking-[0.16em] text-foreground">
              Pilot ID
            </dt>
            <dd class="mt-1 break-all text-foreground-secondary">{{ pilot.id }}</dd>
          </div>
          <div>
            <dt class="text-[11px] font-semibold uppercase tracking-[0.16em] text-foreground">
              Position ID
            </dt>
            <dd class="mt-1 text-foreground-secondary">{{ pilot.positionId ?? '—' }}</dd>
          </div>
        </dl>
      </section>
    </aside>
  </section>
</template>
