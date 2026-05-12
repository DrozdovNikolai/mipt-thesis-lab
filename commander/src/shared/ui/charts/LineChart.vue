<script setup lang="ts">
import { ref } from 'vue'
import {
  CategoryScale,
  Chart,
  Legend,
  LineController,
  LineElement,
  LinearScale,
  PointElement,
  Tooltip,
  type ChartData,
  type ChartOptions,
} from 'chart.js'
import { withExternalChartTooltip } from './chartExternalTooltip'
import { withChartCanvasQuality } from './chartRendering'
import { useCanvasChart } from './useCanvasChart'
Chart.register(
  LineController,
  LineElement,
  PointElement,
  CategoryScale,
  LinearScale,
  Tooltip,
  Legend,
)
const props = withDefaults(
  defineProps<{
    ariaLabel: string
    data: ChartData<'line', number[], string>
    options?: ChartOptions<'line'>
    height?: number
    minWidth?: number
    surfaceClassName?: string
    fillHeight?: boolean
  }>(),
  { height: 320, surfaceClassName: 'bg-surface', fillHeight: false },
)
const canvas = ref<HTMLCanvasElement | null>(null)
useCanvasChart(canvas, () => ({
  type: 'line',
  data: props.data,
  options: withExternalChartTooltip(withChartCanvasQuality(props.options)),
}))
</script>
<template>
  <div
    :class="[
      'chart-scroll-area min-w-0 max-w-full w-full overflow-x-auto',
      fillHeight && 'flex min-h-0 flex-1 flex-col',
      surfaceClassName,
    ]"
  >
    <div
      class="relative"
      :style="{
        width: minWidth ? `max(${minWidth}px, 100%)` : '100%',
        height: fillHeight ? '100%' : `${height}px`,
      }"
    >
      <canvas ref="canvas" role="img" :aria-label="ariaLabel" class="block h-full w-full" />
    </div>
  </div>
</template>
