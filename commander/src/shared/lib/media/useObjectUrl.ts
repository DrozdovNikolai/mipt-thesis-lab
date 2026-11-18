import { onScopeDispose, readonly, ref, toValue, watch } from 'vue'
import type { MaybeRefOrGetter } from 'vue'

type ObjectUrlEntry = {
  url: string
  subscribers: number
  revokeTimer?: ReturnType<typeof setTimeout>
}
const entries = new WeakMap<Blob, ObjectUrlEntry>()

export function useObjectUrl(blob: MaybeRefOrGetter<Blob | null | undefined>) {
  const objectUrl = ref<string | null>(null)
  let release: (() => void) | undefined
  watch(
    () => toValue(blob),
    (next) => {
      release?.()
      release = undefined
      objectUrl.value = null
      if (!next) return
      let entry = entries.get(next)
      if (!entry) {
        entry = { url: URL.createObjectURL(next), subscribers: 0 }
        entries.set(next, entry)
      }
      clearTimeout(entry.revokeTimer)
      entry.subscribers++
      objectUrl.value = entry.url
      const active = entry
      release = () => {
        if (--active.subscribers > 0) return
        active.revokeTimer = setTimeout(() => {
          if (active.subscribers === 0) {
            URL.revokeObjectURL(active.url)
            entries.delete(next)
          }
        }, 0)
      }
    },
    { immediate: true },
  )
  onScopeDispose(() => release?.())
  return readonly(objectUrl)
}
