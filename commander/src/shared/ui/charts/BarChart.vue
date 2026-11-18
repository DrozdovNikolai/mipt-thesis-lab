<script setup lang="ts">
import { ref } from 'vue'
import type { ChartData, ChartOptions } from 'chart.js'
import { withExternalChartTooltip } from './chartExternalTooltip'
import { withStandardBarSizing, createCategorySeparatorPlugin } from './barChartSetup'
import { useCanvasChart } from './useCanvasChart'
const props = withDefaults(
  defineProps<{
    ariaLabel: string
    data: ChartData<'bar', number[], string>
    options?: ChartOptions<'bar'>
    height?: number
    minWidth?: number
    maxHeight?: number
    separatorAfterIndex?: number | null
    fillHeight?: boolean
  }>(),
  { height: 320, separatorAfterIndex: null, fillHeight: false },
)
const canvas = ref<HTMLCanvasElement | null>(null)
useCanvasChart(canvas, () => {
  const separator = createCategorySeparatorPlugin(props.separatorAfterIndex)
  return {
    type: 'bar',
    data: withStandardBarSizing(props.data, props.options?.indexAxis === 'y' ? 'y' : 'x'),
    options: withExternalChartTooltip(props.options),
    plugins: separator ? [separator] : [],
  }
})
</script>
<template>
  <div
    :class="[
      'chart-scroll-area w-full overflow-x-auto bg-surface',
      fillHeight && 'flex min-h-0 flex-1 flex-col',
    ]"
    :style="{
      maxHeight: !fillHeight && maxHeight ? `${maxHeight}px` : undefined,
      overflowY: fillHeight || maxHeight ? 'auto' : undefined,
    }"
  >
    <div
      class="relative w-full"
      :style="{
        minWidth: minWidth ? `${minWidth}px` : undefined,
        height: fillHeight ? '100%' : `${height}px`,
        minHeight: fillHeight ? `${height}px` : undefined,
      }"
    >
      <canvas ref="canvas" role="img" :aria-label="ariaLabel" />
    </div>
  </div>
</template>
