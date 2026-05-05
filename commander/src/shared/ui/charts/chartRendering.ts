import type { ChartOptions, ChartType } from 'chart.js'

const MIN_CHART_DEVICE_PIXEL_RATIO = 2
const MAX_CHART_DEVICE_PIXEL_RATIO = 3

const resolveChartDevicePixelRatio = () => {
  if (typeof window === 'undefined') return 1

  const devicePixelRatio = window.devicePixelRatio || 1
  return Math.min(
    MAX_CHART_DEVICE_PIXEL_RATIO,
    Math.max(MIN_CHART_DEVICE_PIXEL_RATIO, devicePixelRatio),
  )
}

export const withChartCanvasQuality = <TType extends ChartType>(
  options?: ChartOptions<TType>,
): ChartOptions<TType> =>
  ({
    responsive: true,
    maintainAspectRatio: false,
    resizeDelay: 0,
    devicePixelRatio: resolveChartDevicePixelRatio(),
    ...options,
  }) as ChartOptions<TType>
