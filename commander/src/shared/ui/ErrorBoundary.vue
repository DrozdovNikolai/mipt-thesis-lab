<script setup lang="ts">
import { onErrorCaptured, ref, shallowRef } from 'vue'
import { useI18n } from 'vue-i18n'
import { Sentry } from '@/shared/monitoring/sentry'

const { t } = useI18n()
const error = shallowRef<Error | null>(null)
const attempt = ref(0)
onErrorCaptured((caught) => {
  error.value = caught instanceof Error ? caught : new Error(String(caught))
  Sentry.captureException(caught)
  return false
})
function retry() {
  error.value = null
  attempt.value++
}
</script>

<template>
  <main v-if="error" role="alert" class="flex min-h-screen items-center justify-center bg-app px-4">
    <section class="w-full max-w-lg rounded-2xl border border-line bg-surface p-6 shadow-sm">
      <h1 class="text-xl font-semibold text-foreground">{{ t('errors.somethingWentWrong') }}</h1>
      <p class="mt-3 text-sm text-foreground-secondary">{{ t('errors.unexpectedError') }}</p>
      <div class="mt-4 flex gap-3">
        <button
          class="rounded-xl bg-surface-strong px-4 py-2 text-foreground-inverse"
          @click="retry"
        >
          {{ t('actions.tryAgain') }}
        </button>
        <a href="/" class="rounded-xl border border-line px-4 py-2">{{ t('actions.goHome') }}</a>
      </div>
    </section>
  </main>
  <div v-else :key="attempt" class="contents"><slot /></div>
</template>
