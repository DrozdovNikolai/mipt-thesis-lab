<script setup lang="ts" generic="T extends AutocompleteOption">
import { ref, useId } from 'vue'
import {
  ComboboxAnchor,
  ComboboxContent,
  ComboboxInput,
  ComboboxItem,
  ComboboxPortal,
  ComboboxRoot,
} from 'reka-ui'
import type { AutocompleteOption } from './autocomplete'

const props = withDefaults(
  defineProps<{
    label: string
    value: string
    options: readonly T[]
    placeholder?: string
    helperText?: string
    isLoading?: boolean
    disabled?: boolean
    emptyMessage?: string
    inputClassName?: string
    dropdownClassName?: string
  }>(),
  { isLoading: false, disabled: false, emptyMessage: 'No matches found.' },
)
const emit = defineEmits<{ valueChange: [value: string]; optionSelect: [option: T]; clear: [] }>()
const inputId = useId()
const open = ref(false)
// Search and selected option are intentionally independent: the API may return a
// name matched by its email/login, and input edits must not select arbitrary rows.
function select(value: unknown) {
  const option = props.options.find((item) => item.value === value)
  if (option) emit('optionSelect', option)
  open.value = false
}
function clear() {
  emit('valueChange', '')
  emit('clear')
  open.value = false
}
</script>
<template>
  <div class="flex w-full flex-col gap-1.5">
    <label :for="inputId" class="text-xs font-semibold uppercase tracking-wide text-foreground">{{
      label
    }}</label>
    <ComboboxRoot
      v-model:open="open"
      :model-value="null"
      :disabled="disabled"
      ignore-filter
      open-on-focus
      open-on-click
      :reset-search-term-on-blur="false"
      :reset-search-term-on-select="false"
      @update:model-value="select"
    >
      <ComboboxAnchor class="relative">
        <ComboboxInput
          :id="inputId"
          :class="inputClassName"
          :model-value="value"
          :placeholder="placeholder"
          :disabled="disabled"
          :aria-describedby="helperText ? `${inputId}-help` : undefined"
          class="h-10 w-full rounded-xl border border-line bg-surface pl-3 pr-10 text-sm text-foreground outline-none transition focus:border-line-emphasis focus:ring-2 focus:ring-focus disabled:opacity-50"
          @update:model-value="emit('valueChange', $event)"
        />
        <button
          v-if="value && !disabled"
          type="button"
          :aria-label="`Clear ${label}`"
          class="absolute right-2 top-1/2 -translate-y-1/2 rounded px-1.5 text-foreground-secondary hover:bg-surface-muted"
          @click="clear"
        >
          ×
        </button>
      </ComboboxAnchor>
      <ComboboxPortal>
        <ComboboxContent
          position="popper"
          :side-offset="4"
          :class="dropdownClassName"
          class="z-50 max-h-72 w-[var(--reka-combobox-trigger-width)] min-w-48 overflow-y-auto rounded-xl border border-line bg-surface p-1 shadow-lg"
        >
          <p v-if="isLoading" role="status" class="px-3 py-2 text-sm text-foreground-secondary">
            Loading...
          </p>
          <p v-else-if="options.length === 0" class="px-3 py-2 text-sm text-foreground-secondary">
            {{ emptyMessage }}
          </p>
          <ComboboxItem
            v-for="option in options"
            :key="option.value"
            :value="option.value"
            :text-value="option.label"
            class="cursor-pointer rounded-lg px-3 py-2 text-sm text-foreground outline-none data-[highlighted]:bg-surface-muted"
          >
            <div class="flex items-center justify-between gap-2">
              <span class="font-medium">{{ option.label }}</span
              ><span v-if="option.meta" class="text-xs text-foreground-secondary">{{
                option.meta
              }}</span>
            </div>
            <p v-if="option.description" class="mt-0.5 text-xs text-foreground-secondary">
              {{ option.description }}
            </p>
          </ComboboxItem>
        </ComboboxContent>
      </ComboboxPortal>
    </ComboboxRoot>
    <p v-if="helperText" :id="`${inputId}-help`" class="text-xs text-foreground-secondary">
      {{ helperText }}
    </p>
  </div>
</template>
