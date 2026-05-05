import {
  BarController,
  BarElement,
  CategoryScale,
  Chart,
  Legend,
  LinearScale,
  Tooltip,
} from 'chart.js'
import type { ChartData } from 'chart.js'

const STACK_OUTER_RADIUS = 64
const SEPARATOR_STROKE_COLOR = '#B8B8B8'
const VERTICAL_BAR_THICKNESS = 10
const VERTICAL_BAR_CATEGORY_PERCENTAGE = 0.64
const VERTICAL_BAR_PERCENTAGE = 0.74
const HORIZONTAL_BAR_THICKNESS = 10
const HORIZONTAL_BAR_CATEGORY_PERCENTAGE = 0.52
const HORIZONTAL_BAR_PERCENTAGE = 0.66
const chartsWithStackClip = new WeakSet<Chart<'bar', number[], string>>()

const isFiniteChartCoordinate = (value: number | null): value is number =>
  typeof value === 'number' && Number.isFinite(value)

export const withStandardBarSizing = (
  data: ChartData<'bar', number[], string>,
  indexAxis: 'x' | 'y' = 'x',
): ChartData<'bar', number[], string> => ({
  ...data,
  datasets: data.datasets.map((dataset) => ({
    ...dataset,
    barThickness:
      dataset.barThickness ??
      (indexAxis === 'y' ? HORIZONTAL_BAR_THICKNESS : VERTICAL_BAR_THICKNESS),
    maxBarThickness:
      dataset.maxBarThickness ??
      (indexAxis === 'y' ? HORIZONTAL_BAR_THICKNESS : VERTICAL_BAR_THICKNESS),
    categoryPercentage:
      dataset.categoryPercentage ??
      (indexAxis === 'y' ? HORIZONTAL_BAR_CATEGORY_PERCENTAGE : VERTICAL_BAR_CATEGORY_PERCENTAGE),
    barPercentage:
      dataset.barPercentage ??
      (indexAxis === 'y' ? HORIZONTAL_BAR_PERCENTAGE : VERTICAL_BAR_PERCENTAGE),
  })),
})

const stackedBarOuterRadiusPlugin = {
  id: 'stackedBarOuterRadiusClip',
  beforeDatasetsDraw(chart: Chart<'bar', number[], string>) {
    const isStackedChart = Object.values(chart.scales).some(
      (scale) => (scale.options as { stacked?: boolean }).stacked,
    )
    if (!isStackedChart) return

    const datasetMetas = chart.getSortedVisibleDatasetMetas().filter((meta) => meta.type === 'bar')
    if (datasetMetas.length <= 1) return

    const labelsCount = chart.data.labels?.length ?? 0
    if (labelsCount === 0) return

    const isHorizontal = chart.options.indexAxis === 'y'
    const ctx = chart.ctx
    ctx.save()
    ctx.beginPath()

    for (let dataIndex = 0; dataIndex < labelsCount; dataIndex += 1) {
      const elements = datasetMetas.flatMap<BarElement>((meta) => {
        const rawValue = chart.data.datasets[meta.index]?.data[dataIndex]
        const numericValue =
          typeof rawValue === 'number' && Number.isFinite(rawValue) ? rawValue : Number(rawValue)
        if (!Number.isFinite(numericValue) || numericValue <= 0) return []

        const element = meta.data[dataIndex] as BarElement | undefined
        return element ? [element] : []
      })

      if (elements.length === 0) continue

      if (isHorizontal) {
        const geometry = elements.reduce<
          Array<{ x: number; y: number; base: number; height: number }>
        >((acc, element) => {
          const props = element.getProps(['x', 'y', 'base', 'height'], true)
          if (
            !isFiniteChartCoordinate(props.x) ||
            !isFiniteChartCoordinate(props.y) ||
            !isFiniteChartCoordinate(props.base) ||
            !isFiniteChartCoordinate(props.height)
          ) {
            return acc
          }

          acc.push({ x: props.x, y: props.y, base: props.base, height: props.height })
          return acc
        }, [])
        if (geometry.length === 0) continue

        const left = Math.min(...geometry.map((props) => Math.min(props.x, props.base)))
        const right = Math.max(...geometry.map((props) => Math.max(props.x, props.base)))
        const top = Math.min(...geometry.map((props) => props.y - props.height / 2))
        const bottom = Math.max(...geometry.map((props) => props.y + props.height / 2))
        const width = right - left
        const height = bottom - top

        if (width > 0 && height > 0) {
          ctx.roundRect(left, top, width, height, STACK_OUTER_RADIUS)
        }

        continue
      }

      const geometry = elements.reduce<
        Array<{ x: number; y: number; base: number; width: number }>
      >((acc, element) => {
        const props = element.getProps(['x', 'y', 'base', 'width'], true)
        if (
          !isFiniteChartCoordinate(props.x) ||
          !isFiniteChartCoordinate(props.y) ||
          !isFiniteChartCoordinate(props.base) ||
          !isFiniteChartCoordinate(props.width)
        ) {
          return acc
        }

        acc.push({ x: props.x, y: props.y, base: props.base, width: props.width })
        return acc
      }, [])
      if (geometry.length === 0) continue

      const left = Math.min(...geometry.map((props) => props.x - props.width / 2))
      const right = Math.max(...geometry.map((props) => props.x + props.width / 2))
      const top = Math.min(...geometry.map((props) => Math.min(props.y, props.base)))
      const bottom = Math.max(...geometry.map((props) => Math.max(props.y, props.base)))
      const width = right - left
      const height = bottom - top

      if (width > 0 && height > 0) {
        ctx.roundRect(left, top, width, height, STACK_OUTER_RADIUS)
      }
    }

    ctx.clip()
    chartsWithStackClip.add(chart)
  },
  afterDatasetsDraw(chart: Chart<'bar', number[], string>) {
    if (!chartsWithStackClip.has(chart)) return

    chart.ctx.restore()
    chartsWithStackClip.delete(chart)
  },
}

Chart.register(
  BarController,
  BarElement,
  CategoryScale,
  LinearScale,
  Legend,
  Tooltip,
  stackedBarOuterRadiusPlugin,
)

export function createCategorySeparatorPlugin(separatorAfterIndex: number | null) {
  return typeof separatorAfterIndex === 'number'
    ? {
        id: 'categorySeparatorOverlay',
        afterDatasetsDraw(chart: Chart<'bar', number[], string>) {
          if (chart.options.indexAxis !== 'y') return
          const labelsCount = chart.data.labels?.length ?? 0
          if (separatorAfterIndex < 0 || separatorAfterIndex >= labelsCount - 1) return

          const yScale = chart.scales.y
          if (!yScale) return

          const currentCenter = yScale.getPixelForValue(separatorAfterIndex)
          const nextCenter = yScale.getPixelForValue(separatorAfterIndex + 1)
          if (!Number.isFinite(currentCenter) || !Number.isFinite(nextCenter)) return

          const separatorY = (currentCenter + nextCenter) / 2
          const { left, right } = chart.chartArea
          const ctx = chart.ctx
          ctx.save()
          ctx.strokeStyle = SEPARATOR_STROKE_COLOR
          ctx.lineWidth = 1.5
          ctx.setLineDash([6, 6])
          ctx.beginPath()
          ctx.moveTo(left, separatorY)
          ctx.lineTo(right, separatorY)
          ctx.stroke()
          ctx.restore()
        },
      }
    : null
}
