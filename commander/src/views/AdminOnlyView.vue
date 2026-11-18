<script setup lang="ts">
import { useI18n } from 'vue-i18n'
const { t } = useI18n()
</script>
<template>
  <section class="rounded-2xl border border-line bg-surface p-6 shadow-sm">
    <h2 class="text-2xl font-semibold tracking-tight text-foreground">{{ t('routes.admin') }}</h2>
    <p class="mt-2 text-sm text-foreground">{{ t('admin.description') }}</p>
  </section>
</template>
