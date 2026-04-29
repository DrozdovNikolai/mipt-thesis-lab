<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

const props = withDefaults(
  defineProps<{
    contentScrollAreaClassName?: string
    measureWrapperClassName?: string
    enableStickyScrollbar?: boolean
    scrollbarAriaLabel?: string
  }>(),
  {
    contentScrollAreaClassName: 'sticky-horizontal-scrollbar overflow-x-auto',
    measureWrapperClassName: 'min-w-full w-max',
    enableStickyScrollbar: false,
    scrollbarAriaLabel: 'Scroll horizontally',
  },
)

const contentScroll = ref<HTMLElement | null>(null)
const contentMeasure = ref<HTMLElement | null>(null)
const bottomScroll = ref<HTMLElement | null>(null)
const hasOverflow = ref(false)
const contentWidth = ref(0)
let observer: ResizeObserver | undefined
let frame: number | undefined

function sync(source: HTMLElement | null, target: HTMLElement | null) {
  if (source && target && source.scrollLeft !== target.scrollLeft)
    target.scrollLeft = source.scrollLeft
}
function updateMetrics() {
  if (!props.enableStickyScrollbar || !contentScroll.value || !contentMeasure.value) {
    hasOverflow.value = false
    return
  }
  const width = Math.ceil(contentMeasure.value.scrollWidth)
  const maxScrollLeft = Math.max(0, width - contentScroll.value.clientWidth)
  contentWidth.value = width
  hasOverflow.value = maxScrollLeft > 1
  contentScroll.value.scrollLeft = Math.min(contentScroll.value.scrollLeft, maxScrollLeft)
  void nextTick(() => sync(contentScroll.value, bottomScroll.value))
}
onMounted(() => {
  observer = new ResizeObserver(updateMetrics)
  if (contentScroll.value) observer.observe(contentScroll.value)
  if (contentMeasure.value) observer.observe(contentMeasure.value)
  frame = requestAnimationFrame(updateMetrics)
})
watch(() => props.enableStickyScrollbar, updateMetrics, { flush: 'post' })
onBeforeUnmount(() => {
  observer?.disconnect()
  if (frame !== undefined) cancelAnimationFrame(frame)
})
</script>
<template>
  <div
    ref="contentScroll"
    :class="contentScrollAreaClassName"
    @scroll.passive="sync(contentScroll, bottomScroll)"
  >
    <div ref="contentMeasure" :class="measureWrapperClassName"><slot /></div>
  </div>
  <div
    v-if="enableStickyScrollbar && hasOverflow"
    class="sticky bottom-0 z-10 border-t border-line bg-surface/95 px-4 py-2 backdrop-blur"
  >
    <div
      ref="bottomScroll"
      class="sticky-horizontal-scrollbar h-4 w-full overflow-x-auto overflow-y-hidden"
      :aria-label="scrollbarAriaLabel"
      @scroll.passive="sync(bottomScroll, contentScroll)"
    >
      <div :style="{ width: `${Math.max(contentWidth, 1)}px`, height: '1px' }" aria-hidden="true" />
    </div>
  </div>
</template>
