import { onBeforeUnmount, onMounted, toRaw, watch, type Ref } from 'vue'
import {
  Chart,
  type ChartConfiguration,
  type ChartType,
  type ChartOptions,
  type DefaultDataPoint,
} from 'chart.js'
import { removeExternalChartTooltip } from './chartExternalTooltip'

// Chart.js owns and mutates its configuration. Never hand it Vue proxies or the
// arrays in the query cache; callbacks must remain callable during the copy.
function copyConfig<T>(value: T): T {
  if (Array.isArray(value)) return value.map((item) => copyConfig(item)) as T
  if (value && typeof value === 'object') {
    const raw = toRaw(value)
    if (Object.getPrototypeOf(raw) === Object.prototype)
      return Object.fromEntries(
        Object.entries(raw).map(([key, item]) => [key, copyConfig(item)]),
      ) as T
  }
  return value
}
export function useCanvasChart<T extends ChartType, D = DefaultDataPoint<T>>(
  canvas: Ref<HTMLCanvasElement | null>,
  config: () => ChartConfiguration<T, D, string>,
) {
  let chart: Chart<T, D, string> | null = null
  function update() {
    if (!canvas.value) return
    const current = config()
    const next = copyConfig({ ...current, plugins: current.plugins ?? [] })
    if (!chart) chart = new Chart(canvas.value, next)
    else {
      removeExternalChartTooltip(chart as unknown as Chart<ChartType>)
      chart.data = next.data
      chart.options = next.options ?? ({} as ChartOptions<T>)
      chart.config.plugins?.splice(0, chart.config.plugins.length, ...(next.plugins ?? []))
      chart.update('none')
    }
  }
  onMounted(update)
  watch(config, update, { flush: 'post' })
  onBeforeUnmount(() => {
    removeExternalChartTooltip(chart as unknown as Chart<ChartType> | null)
    chart?.destroy()
    chart = null
  })
}
