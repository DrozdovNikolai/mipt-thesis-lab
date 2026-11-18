<script setup lang="ts">
import { APP_BRAND } from './brand'
defineProps<{ imageClassName?: string }>()
</script>

<template>
  <img
    v-if="APP_BRAND.logoSrc"
    :src="APP_BRAND.logoSrc"
    :class="imageClassName"
    :alt="APP_BRAND.logoLabel"
  />
  <span v-else class="brand-logo" role="img" :aria-label="APP_BRAND.logoLabel">
    <span class="brand-logo__digit brand-logo__digit--first">5</span
    ><span class="brand-logo__digit brand-logo__digit--second">5</span
    ><span class="brand-logo__text">NORD</span>
  </span>
</template>
