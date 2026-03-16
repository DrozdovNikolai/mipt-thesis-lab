import { effectScope, nextTick, ref, shallowRef } from 'vue'
import { afterEach, expect, it, vi } from 'vitest'
import { useObjectUrl } from '@/shared/lib/media/useObjectUrl'
import { useDebouncedValue } from '@/shared/lib/useDebouncedValue'

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

it('keeps a shared Blob URL until the last consumer leaves and reuses it on immediate remount', async () => {
  vi.useFakeTimers()
  const create = vi.fn(() => 'blob:shared')
  const revoke = vi.fn()
  vi.stubGlobal('URL', { createObjectURL: create, revokeObjectURL: revoke })
  const blob = shallowRef(new Blob(['image']))
  const first = effectScope()
  const second = effectScope()
  const a = first.run(() => useObjectUrl(blob))!
  const b = second.run(() => useObjectUrl(blob))!
  expect(a.value).toBe('blob:shared')
  expect(b.value).toBe(a.value)
  expect(create).toHaveBeenCalledTimes(1)
  first.stop()
  vi.runAllTimers()
  expect(revoke).not.toHaveBeenCalled()
  second.stop()
  const third = effectScope()
  third.run(() => useObjectUrl(blob))
  vi.runAllTimers()
  expect(revoke).not.toHaveBeenCalled()
  expect(create).toHaveBeenCalledTimes(1)
  third.stop()
  vi.runAllTimers()
  expect(revoke).toHaveBeenCalledExactlyOnceWith('blob:shared')
  await nextTick()
})

it('debounces to the latest input and cancels updates when the owner unmounts', async () => {
  vi.useFakeTimers()
  const scope = effectScope()
  const input = ref('')
  const value = scope.run(() => useDebouncedValue(input, 350))!
  input.value = 'a'
  await nextTick()
  vi.advanceTimersByTime(200)
  input.value = 'ab'
  await nextTick()
  vi.advanceTimersByTime(349)
  expect(value.value).toBe('')
  vi.advanceTimersByTime(1)
  expect(value.value).toBe('ab')
  input.value = 'abc'
  await nextTick()
  scope.stop()
  vi.runAllTimers()
  expect(value.value).toBe('ab')
})
