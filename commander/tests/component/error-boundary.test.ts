import { afterEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h, nextTick } from 'vue'
import { mount } from '@vue/test-utils'
import ErrorBoundary from '@/shared/ui/ErrorBoundary.vue'
import { i18n } from '@/shared/i18n'
const capture = vi.hoisted(() => vi.fn())
vi.mock('@/shared/monitoring/sentry', () => ({ Sentry: { captureException: capture } }))
afterEach(() => {
  i18n.global.locale.value = 'en'
  capture.mockReset()
})

describe('Vue recovery boundary', () => {
  it('captures once, shows localized recovery and remounts a recovered child', async () => {
    let fail = true
    const Child = defineComponent({
      setup() {
        if (fail) throw new Error('synthetic child error')
        return () => h('p', 'Recovered')
      },
    })
    i18n.global.locale.value = 'ru'
    const wrapper = mount(ErrorBoundary, {
      global: { plugins: [i18n] },
      slots: { default: () => h(Child) },
    })
    await nextTick()
    expect(wrapper.get('[role="alert"]').text()).toContain('Что-то пошло не так')
    expect(capture).toHaveBeenCalledTimes(1)
    fail = false
    await wrapper.get('button').trigger('click')
    expect(wrapper.text()).toBe('Recovered')
    expect(capture).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })
})
