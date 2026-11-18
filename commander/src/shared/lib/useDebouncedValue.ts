import { onScopeDispose, readonly, ref, toValue, watch } from 'vue'
import type { MaybeRefOrGetter, Ref } from 'vue'

export function useDebouncedValue<T>(
  value: MaybeRefOrGetter<T>,
  delayMs: number,
): Readonly<Ref<T>> {
  const debounced = ref(toValue(value)) as Ref<T>
  let timer: ReturnType<typeof setTimeout> | undefined
  watch(
    () => toValue(value),
    (next) => {
      clearTimeout(timer)
      timer = setTimeout(() => {
        debounced.value = next
      }, delayMs)
    },
  )
  onScopeDispose(() => clearTimeout(timer))
  return readonly(debounced) as Readonly<Ref<T>>
}
