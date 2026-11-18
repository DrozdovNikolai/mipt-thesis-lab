import type { Chart, ChartOptions, ChartType, TooltipLabelStyle, TooltipModel } from 'chart.js'

const TOOLTIP_VIEWPORT_PADDING = 12
const TOOLTIP_OFFSET = 16
const tooltipElementRegistry = new WeakMap<Chart<ChartType>, HTMLDivElement>()

const resolveTooltipLabelColor = (
  color: TooltipLabelStyle['backgroundColor'] | TooltipLabelStyle['borderColor'],
  fallbackColor: string,
) => {
  if (typeof color === 'string' && color.trim()) return color
  if (Array.isArray(color)) {
    const firstColor = color.find((value) => typeof value === 'string' && value.trim())
    if (typeof firstColor === 'string') return firstColor
  }
  return fallbackColor
}

const createTooltipElement = () => {
  const element = document.createElement('div')
  element.setAttribute('data-chart-external-tooltip', 'true')
  Object.assign(element.style, {
    position: 'fixed',
    left: '0',
    top: '0',
    zIndex: '9999',
    maxWidth: 'min(340px, calc(100vw - 24px))',
    borderRadius: '14px',
    background: '#0f172a',
    color: '#f8fafc',
    boxShadow: '0 18px 48px rgba(15, 23, 42, 0.28)',
    padding: '14px 16px',
    pointerEvents: 'none',
    opacity: '0',
    visibility: 'hidden',
    transition: 'opacity 120ms ease',
    transform: 'translate(-9999px, -9999px)',
  } satisfies Partial<CSSStyleDeclaration>)
  document.body.appendChild(element)
  return element
}

const getTooltipElement = (chart: Chart<ChartType>) => {
  const existingElement = tooltipElementRegistry.get(chart)
  if (existingElement) return existingElement

  const nextElement = createTooltipElement()
  tooltipElementRegistry.set(chart, nextElement)
  return nextElement
}

const clearTooltipElement = (tooltipElement: HTMLDivElement) => {
  tooltipElement.style.opacity = '0'
  tooltipElement.style.visibility = 'hidden'
  tooltipElement.style.transform = 'translate(-9999px, -9999px)'
}

const appendTooltipTitle = (tooltipElement: HTMLDivElement, lines: string[]) => {
  if (lines.length === 0) return

  const titleContainer = document.createElement('div')
  titleContainer.style.display = 'grid'
  titleContainer.style.gap = '4px'
  titleContainer.style.marginBottom = '10px'

  lines.forEach((line) => {
    const lineElement = document.createElement('div')
    lineElement.textContent = line
    lineElement.style.fontSize = '15px'
    lineElement.style.fontWeight = '700'
    lineElement.style.lineHeight = '1.3'
    titleContainer.appendChild(lineElement)
  })

  tooltipElement.appendChild(titleContainer)
}

const appendTooltipBody = (tooltipElement: HTMLDivElement, tooltip: TooltipModel<ChartType>) => {
  if (tooltip.body.length === 0) return

  const bodyContainer = document.createElement('div')
  bodyContainer.style.display = 'grid'
  bodyContainer.style.gap = '8px'

  tooltip.body.forEach((bodyItem, index) => {
    bodyItem.lines.forEach((line, lineIndex) => {
      const rowElement = document.createElement('div')
      rowElement.style.display = 'flex'
      rowElement.style.alignItems = 'center'
      rowElement.style.gap = '8px'
      rowElement.style.fontSize = '14px'
      rowElement.style.fontWeight = '600'
      rowElement.style.lineHeight = '1.35'

      const bulletElement = document.createElement('span')
      bulletElement.style.width = '8px'
      bulletElement.style.height = '8px'
      bulletElement.style.flexShrink = '0'
      bulletElement.style.borderRadius = '9999px'

      if (lineIndex === 0 && tooltip.labelColors[index]) {
        const labelColor = tooltip.labelColors[index]
        bulletElement.style.background = resolveTooltipLabelColor(
          labelColor.backgroundColor,
          '#cbd5e1',
        )
        bulletElement.style.border = `1px solid ${resolveTooltipLabelColor(labelColor.borderColor, '#0f172a')}`
      } else {
        bulletElement.style.opacity = '0'
      }

      const lineElement = document.createElement('span')
      lineElement.textContent = line

      rowElement.appendChild(bulletElement)
      rowElement.appendChild(lineElement)
      bodyContainer.appendChild(rowElement)
    })
  })

  tooltipElement.appendChild(bodyContainer)
}

const appendTooltipFooter = (tooltipElement: HTMLDivElement, lines: string[]) => {
  if (lines.length === 0) return

  const footerContainer = document.createElement('div')
  footerContainer.style.display = 'grid'
  footerContainer.style.gap = '4px'
  footerContainer.style.marginTop = '10px'
  footerContainer.style.paddingTop = '10px'
  footerContainer.style.borderTop = '1px solid rgba(148, 163, 184, 0.28)'
  footerContainer.style.color = '#cbd5e1'

  lines.forEach((line) => {
    const lineElement = document.createElement('div')
    lineElement.textContent = line
    lineElement.style.fontSize = '12px'
    lineElement.style.fontWeight = '600'
    lineElement.style.lineHeight = '1.35'
    footerContainer.appendChild(lineElement)
  })

  tooltipElement.appendChild(footerContainer)
}

const renderTooltipContent = (tooltipElement: HTMLDivElement, tooltip: TooltipModel<ChartType>) => {
  tooltipElement.replaceChildren()
  appendTooltipTitle(tooltipElement, tooltip.title)
  appendTooltipBody(tooltipElement, tooltip)
  appendTooltipFooter(tooltipElement, tooltip.footer)
}

const positionTooltipElement = (
  chart: Chart<ChartType>,
  tooltip: TooltipModel<ChartType>,
  tooltipElement: HTMLDivElement,
) => {
  const canvasBounds = chart.canvas.getBoundingClientRect()
  const anchorX = canvasBounds.left + tooltip.caretX
  const anchorY = canvasBounds.top + tooltip.caretY

  let left = anchorX + TOOLTIP_OFFSET
  let top = anchorY - tooltipElement.offsetHeight / 2

  if (left + tooltipElement.offsetWidth > window.innerWidth - TOOLTIP_VIEWPORT_PADDING) {
    left = anchorX - tooltipElement.offsetWidth - TOOLTIP_OFFSET
  }

  left = Math.max(
    TOOLTIP_VIEWPORT_PADDING,
    Math.min(left, window.innerWidth - tooltipElement.offsetWidth - TOOLTIP_VIEWPORT_PADDING),
  )
  top = Math.max(
    TOOLTIP_VIEWPORT_PADDING,
    Math.min(top, window.innerHeight - tooltipElement.offsetHeight - TOOLTIP_VIEWPORT_PADDING),
  )

  tooltipElement.style.left = `${left}px`
  tooltipElement.style.top = `${top}px`
  tooltipElement.style.visibility = 'visible'
  tooltipElement.style.opacity = '1'
  tooltipElement.style.transform = 'translate(0, 0)'
}

export const withExternalChartTooltip = <TType extends ChartType>(
  options?: ChartOptions<TType>,
): ChartOptions<TType> => {
  const tooltipOptions = options?.plugins?.tooltip

  return {
    ...options,
    plugins: {
      ...options?.plugins,
      tooltip: {
        ...tooltipOptions,
        enabled: false,
        external: (context) => {
          const tooltipElement = getTooltipElement(context.chart as Chart<ChartType>)
          if (context.tooltip.opacity === 0) {
            clearTooltipElement(tooltipElement)
            return
          }

          renderTooltipContent(tooltipElement, context.tooltip as TooltipModel<ChartType>)
          positionTooltipElement(
            context.chart as Chart<ChartType>,
            context.tooltip as TooltipModel<ChartType>,
            tooltipElement,
          )
        },
      },
    },
  } as ChartOptions<TType>
}

export const removeExternalChartTooltip = (chart: Chart<ChartType> | null) => {
  if (!chart) return

  const tooltipElement = tooltipElementRegistry.get(chart)
  if (!tooltipElement) return

  tooltipElement.remove()
  tooltipElementRegistry.delete(chart)
}
