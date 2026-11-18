<script setup lang="ts">
import { APP_BRAND } from './brand'
</script>

<template>
  <span class="brand-logo" role="img" :aria-label="APP_BRAND.logoLabel">
    <span class="brand-logo__digit brand-logo__digit--first">5</span
    ><span class="brand-logo__digit brand-logo__digit--second">5</span
    ><span class="brand-logo__text">NORD</span>
  </span>
</template>
