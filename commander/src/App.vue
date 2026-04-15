<script setup lang="ts">
import { computed, watch } from 'vue'
import { RouterView, useRoute, useRouter } from 'vue-router'
import { useSessionService } from '@/app/context'
import { routeAllowed } from '@/app/guards'
import AuthView from '@/views/AuthView.vue'

const session = useSessionService()
const route = useRoute()
const router = useRouter()
const allowed = computed(() => routeAllowed(route, session))
watch(
  () => [session.store.isReady, session.store.privileges.join('|'), route.fullPath],
  () => {
    if (session.store.isReady && !allowed.value) void router.replace('/forbidden')
  },
)
</script>
<template>
  <main
    v-if="session.store.status === 'restoring'"
    class="flex min-h-screen items-center justify-center bg-app px-4"
  >
    <p class="text-sm font-medium text-foreground">loading</p>
  </main>
  <AuthView v-else-if="!session.store.tokens" />
  <main
    v-else-if="session.store.status === 'error'"
    class="flex min-h-screen items-center justify-center bg-app px-4"
  >
    <section
      role="alert"
      class="w-full max-w-md rounded-2xl border border-line-danger bg-surface p-6 shadow-sm"
    >
      <h1 class="text-lg font-semibold text-foreground">Session check failed</h1>
      <p class="mt-2 text-sm text-foreground">{{ session.store.error }}</p>
      <div class="mt-4 flex gap-3">
        <button
          type="button"
          class="rounded-xl bg-surface-strong px-4 py-2 text-foreground-inverse"
          @click="session.retry"
        >
          Try again
        </button>
        <button
          type="button"
          class="rounded-xl border border-line-strong px-4 py-2"
          @click="session.logout"
        >
          Back to login
        </button>
      </div>
    </section>
  </main>
  <RouterView v-else-if="session.store.isReady && allowed" :key="session.store.generation" />
  <main v-else class="flex min-h-screen items-center justify-center bg-app px-4">
    <p class="text-sm font-medium text-foreground">loading</p>
  </main>
</template>
