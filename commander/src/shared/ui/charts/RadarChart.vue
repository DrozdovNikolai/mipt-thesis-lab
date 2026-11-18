<script setup lang="ts">
import { ref } from 'vue'
import {
  Chart,
  Filler,
  Legend,
  LineElement,
  PointElement,
  RadarController,
  RadialLinearScale,
  Tooltip,
  type ChartData,
  type ChartOptions,
} from 'chart.js'
import { withExternalChartTooltip } from './chartExternalTooltip'
import { withChartCanvasQuality } from './chartRendering'
import { useCanvasChart } from './useCanvasChart'
Chart.register(
  RadarController,
  LineElement,
  PointElement,
  RadialLinearScale,
  Tooltip,
  Legend,
  Filler,
)
const props = withDefaults(
  defineProps<{
    ariaLabel: string
    data: ChartData<'radar', (number | null)[], string>
    options?: ChartOptions<'radar'>
    height?: number
  }>(),
  { height: 360 },
)
const canvas = ref<HTMLCanvasElement | null>(null)
useCanvasChart(canvas, () => ({
  type: 'radar',
  data: props.data,
  options: withExternalChartTooltip(withChartCanvasQuality(props.options)),
}))
</script>
<template>
  <div class="relative w-full max-w-full" :style="{ height: `${height}px` }">
    <canvas ref="canvas" role="img" :aria-label="ariaLabel" class="block h-full w-full" />
  </div>
</template>
