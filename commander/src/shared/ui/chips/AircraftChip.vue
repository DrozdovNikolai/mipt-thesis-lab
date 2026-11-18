<script setup lang="ts">
import { computed } from 'vue'
const props = defineProps<{ colorHex?: string | null }>()
const tone = computed(() => {
  const raw = props.colorHex?.trim() ?? ''
  const withHash = raw.startsWith('#') ? raw : `#${raw}`
  const color = /^#[0-9A-F]{6}$/i.test(withHash) ? withHash.toUpperCase() : '#284692'
  return { color, borderColor: color, backgroundColor: `${color}19` }
})
</script>
<template>
  <span class="inline-flex items-center rounded-full border font-semibold" :style="tone"
    ><slot
  /></span>
</template>
