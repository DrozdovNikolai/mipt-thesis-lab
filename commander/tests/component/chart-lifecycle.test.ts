import { describe, expect, it, vi } from 'vitest'
import { defineComponent, h, nextTick, ref } from 'vue'
import { mount } from '@vue/test-utils'
import type { ChartConfiguration } from 'chart.js'
import { useCanvasChart } from '@/shared/ui/charts/useCanvasChart'

const instances = vi.hoisted(
  () =>
    [] as {
      destroy: ReturnType<typeof vi.fn>
      update: ReturnType<typeof vi.fn>
      data: ChartConfiguration<'bar'>['data']
    }[],
)
const removeTooltip = vi.hoisted(() => vi.fn())
vi.mock('@/shared/ui/charts/chartExternalTooltip', () => ({
  removeExternalChartTooltip: removeTooltip,
}))
vi.mock('chart.js', () => ({
  Chart: class {
    config: ChartConfiguration<'bar'>
    data: ChartConfiguration<'bar'>['data']
    options = {}
    update = vi.fn()
    destroy = vi.fn()
    constructor(_canvas: HTMLCanvasElement, config: ChartConfiguration<'bar'>) {
      this.config = config
      this.data = config.data
      instances.push(this)
      // A third party may annotate or reorder its owned datasets.
      this.data.datasets[0]!.data.push(99)
    }
  },
}))

describe('chart ownership and lifecycle', () => {
  it('isolates reactive data, updates the existing instance, and disposes 20 route mounts', async () => {
    const config = ref<ChartConfiguration<'bar', number[], string>>({
      type: 'bar',
      data: { labels: ['A'], datasets: [{ data: [1] }] },
    })
    const View = defineComponent({
      setup() {
        const canvas = ref<HTMLCanvasElement | null>(null)
        useCanvasChart(canvas, () => config.value)
        return () => h('canvas', { ref: canvas })
      },
    })
    for (let index = 0; index < 20; index++) {
      const wrapper = mount(View)
      const instance = instances.at(-1)!
      expect(config.value.data.datasets[0]!.data).not.toContain(99)
      config.value = { type: 'bar', data: { labels: ['B'], datasets: [{ data: [index] }] } }
      await nextTick()
      expect(instance.update).toHaveBeenCalledWith('none')
      expect(instance.data.datasets[0]!.data).toEqual([index])
      expect(instances).toHaveLength(index + 1)
      wrapper.unmount()
      expect(instance.destroy).toHaveBeenCalledTimes(1)
      expect(removeTooltip).toHaveBeenCalledWith(instance)
    }
  })
})
