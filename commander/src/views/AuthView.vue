<script setup lang="ts">
import { computed, reactive } from 'vue'
import { useI18n } from 'vue-i18n'
import { useSessionService } from '@/app/context'

const session = useSessionService()
const { t } = useI18n()
const form = reactive({ login: '', password: '' })
const isPending = computed(
  () => session.store.status === 'authenticating' || session.store.status === 'loading-profile',
)
const statusLabel = computed(() => t(`status.${isPending.value ? 'loading' : 'unauthorized'}`))
const fieldClassName =
  'h-11 w-full rounded-xl border border-line-strong bg-surface px-3 text-sm text-foreground outline-none transition focus:border-line-emphasis focus:ring-2 focus:ring-focus'
async function submit() {
  if (!form.login || !form.password || isPending.value) return
  await session.login({ ...form })
  if (session.store.isReady) form.password = ''
}
</script>

<template>
  <main class="flex min-h-screen items-center justify-center bg-app px-4 py-8">
    <section class="w-full max-w-md rounded-2xl border border-line bg-surface p-6 shadow-sm">
      <header class="mb-5 space-y-1">
        <h1 class="text-2xl font-semibold tracking-tight text-foreground">{{ t('auth.title') }}</h1>
        <p class="text-sm text-foreground">
          {{ t('statusLabel') }}:
          <span class="font-medium text-foreground-secondary">{{ statusLabel }}</span>
        </p>
      </header>
      <form class="space-y-4" @submit.prevent="submit">
        <label class="flex flex-col gap-1.5">
          <span class="text-xs font-semibold uppercase tracking-wide text-foreground">{{
            t('auth.login')
          }}</span>
          <input
            v-model="form.login"
            placeholder="admin"
            autocomplete="username"
            :class="fieldClassName"
          />
        </label>
        <label class="flex flex-col gap-1.5">
          <span class="text-xs font-semibold uppercase tracking-wide text-foreground">{{
            t('auth.password')
          }}</span>
          <input
            v-model="form.password"
            type="password"
            autocomplete="current-password"
            :class="fieldClassName"
          />
        </label>
        <div class="flex flex-wrap items-center gap-2 pt-1">
          <button
            type="submit"
            :disabled="!form.login || !form.password || isPending"
            class="inline-flex h-11 items-center rounded-xl bg-surface-strong px-4 text-sm font-medium text-foreground-inverse transition hover:bg-surface-strong-hover disabled:cursor-not-allowed disabled:opacity-50"
          >
            {{ t('auth.signIn') }}{{ isPending ? '...' : '' }}
          </button>
        </div>
      </form>
      <p
        v-if="session.store.error"
        role="alert"
        class="mt-4 rounded-xl border border-line-danger bg-danger-soft px-3 py-2 text-sm text-danger"
      >
        {{ t('auth.error') }}: {{ session.store.error }}
      </p>
    </section>
  </main>
</template>
