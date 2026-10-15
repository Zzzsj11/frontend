<script setup lang="ts">
import { computed, useId } from 'vue'
import {
  SelectContent,
  SelectGroup,
  SelectIcon,
  SelectItem,
  SelectItemIndicator,
  SelectItemText,
  SelectLabel,
  SelectPortal,
  SelectRoot,
  SelectTrigger,
  SelectValue,
  SelectViewport,
} from 'reka-ui'
import AppIcon from '../AppIcon.vue'
const props = withDefaults(
  defineProps<{
    modelValue: string
    groups: Array<{
      label: string
      items: Array<{ value: string; label: string; disabled?: boolean }>
    }>
    icon?: 'movie' | 'image' | null
    placeholder?: string
    triggerAttrs?: Record<string, unknown>
    name?: string
    required?: boolean
    label?: string
    ariaLabel?: string
    disabled?: boolean
    id?: string
    compact?: boolean
  }>(),
  {
    name: undefined,
    icon: 'movie',
    label: '',
    ariaLabel: '',
    disabled: false,
    id: '',
    compact: false,
    placeholder: '请选择',
    triggerAttrs: () => ({}),
  },
)
const emit = defineEmits<{ 'update:modelValue': [value: string] }>()
const generatedId = useId()
const selectId = computed(() => props.id || generatedId)
const selectedLabel = computed(
  () =>
    props.groups.flatMap((group) => group.items).find((item) => item.value === props.modelValue)
      ?.label ?? props.placeholder,
)
const updateModel = (value: unknown) => {
  if (typeof value === 'string') emit('update:modelValue', value)
}
</script>

<template>
  <div class="generation-model-field" :class="{ compact }" @click.stop>
    <label v-if="label" class="generation-model-label" :for="selectId">{{ label }}</label>
    <SelectRoot
      :model-value="modelValue"
      :name="name"
      :required="required"
      :disabled="disabled || !groups.length"
      @update:model-value="updateModel"
    >
      <SelectTrigger
        v-bind="triggerAttrs"
        :id="selectId"
        class="generation-model-trigger"
        :aria-label="ariaLabel || undefined"
      >
        <AppIcon v-if="icon" :name="icon" :size="compact ? 14 : 16" />
        <SelectValue class="generation-model-value">{{ selectedLabel }}</SelectValue>
        <SelectIcon class="generation-model-chevron" aria-hidden="true">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
            <path
              d="m6 9 6 6 6-6"
              stroke="currentColor"
              stroke-width="2"
              stroke-linecap="round"
              stroke-linejoin="round"
            />
          </svg>
        </SelectIcon>
      </SelectTrigger>
      <SelectPortal>
        <SelectContent
          class="generation-model-menu"
          position="popper"
          :side-offset="6"
          align="start"
          @click.stop
        >
          <SelectViewport class="generation-model-viewport">
            <SelectGroup v-for="group in groups" :key="group.label" class="generation-model-group">
              <SelectLabel v-if="group.label" class="generation-model-group-label">{{
                group.label
              }}</SelectLabel>
              <SelectItem
                v-for="item in group.items"
                :key="item.value"
                class="generation-model-item"
                :value="item.value"
                :disabled="item.disabled"
              >
                <SelectItemIndicator class="generation-model-check" aria-hidden="true"
                  >✓</SelectItemIndicator
                >
                <SelectItemText class="generation-model-item-text">{{ item.label }}</SelectItemText>
              </SelectItem>
            </SelectGroup>
          </SelectViewport>
        </SelectContent>
      </SelectPortal>
    </SelectRoot>
    <slot name="after" />
  </div>
</template>

<style scoped>
.generation-model-field {
  min-width: 0;
  width: 100%;
}
.generation-model-label {
  display: block;
  margin-bottom: 7px;
  color: var(--text-secondary);
  font-size: var(--font-sm);
}
.generation-model-trigger {
  display: flex;
  width: 100%;
  min-height: 44px;
  align-items: center;
  gap: 10px;
  padding: 9px 12px;
  border: 1px solid var(--border-dark);
  border-radius: var(--radius-sm);
  background: var(--surface);
  color: var(--text);
  font-family: inherit;
  font-size: var(--font-md);
  font-weight: 400;
  text-align: left;
  cursor: pointer;
  transition:
    border-color 0.16s,
    box-shadow 0.16s,
    background 0.16s;
}
.generation-model-trigger:hover,
.generation-model-trigger[data-state='open'] {
  border-color: var(--primary);
  background: var(--primary-light);
}
.generation-model-trigger:focus-visible {
  outline: none;
  box-shadow: 0 0 0 3px var(--primary-light);
  border-color: var(--primary);
}
.generation-model-trigger[data-disabled] {
  opacity: 0.55;
  cursor: not-allowed;
}
.generation-model-trigger .app-icon {
  flex: none;
  color: var(--primary);
}
.generation-model-value {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.generation-model-chevron {
  flex: none;
  color: var(--text-secondary);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  margin-left: auto;
  line-height: 0;
}
.compact .generation-model-trigger {
  min-height: 42px;
  padding: 7px 10px;
  font-size: var(--font-sm);
}
</style>
