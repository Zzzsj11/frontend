<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { PopoverRoot, PopoverTrigger, PopoverPortal, PopoverContent } from 'reka-ui'
import { useGenerationPreferences, type GenerationModality } from '../stores/generationPreferences'
const props = withDefaults(
  defineProps<{
    beforeSelect?: (model: string) => boolean
    modelValue: string
    modality: GenerationModality
    groups: Array<{
      label: string
      items: Array<{ value: string; label: string; disabled?: boolean }>
    }>
    label?: string
    ariaLabel?: string
    disabled?: boolean
    id?: string
    compact?: boolean
  }>(),
  { label: '', ariaLabel: '模型', disabled: false, id: '', compact: false },
)
const emit = defineEmits<{ 'update:modelValue': [value: string] }>()
const preferences = useGenerationPreferences()
const open = ref(false)
const expanded = ref('')
const channelLoading = ref(false)
const channelError = ref(false)
const selected = computed(() => preferences.selections[props.modality])
const model = computed(() => selected.value?.model || props.modelValue)
const labelText = computed(
  () =>
    props.groups.flatMap((g) => g.items).find((i) => i.value === model.value)?.label || model.value,
)
onMounted(() => {
  if (model.value !== props.modelValue) emit('update:modelValue', model.value)
})
const channelText = computed(() => {
  const channel = selected.value?.channel
  return channel
    ? preferences.channels[model.value]?.find((c) => c.channel === channel)?.name || channel
    : '自动（平台推荐）'
})
watch(
  model,
  (value) => {
    if (value !== props.modelValue) emit('update:modelValue', value)
  },
  { immediate: true },
)
watch(
  () => props.modelValue,
  () => {
    if (model.value !== props.modelValue) emit('update:modelValue', model.value)
  },
)
watch(
  [model, () => selected.value?.channel],
  ([value, channel]) => {
    if (channel && value && !preferences.channels[value]) {
      void preferences.loadChannels(value).catch(() => {
        // Keep the selected key visible when discovery is temporarily unavailable.
      })
    }
  },
  { immediate: true },
)
async function expand(value: string) {
  expanded.value = value
  channelLoading.value = true
  channelError.value = false
  try {
    await preferences.loadChannels(value)
  } catch {
    channelError.value = true
  } finally {
    channelLoading.value = false
  }
}
async function choose(value: string, channel: string | null) {
  if (props.beforeSelect && !props.beforeSelect(value)) {
    open.value = false
    return
  }
  try {
    await preferences.save(props.modality, { model: value, channel })
    emit('update:modelValue', value)
    open.value = false
  } catch {
    /* API 客户端统一展示错误，保留原选择。 */
  }
}
</script>
<template>
  <div class="model-channel-field" @click.stop>
    <label v-if="label" :for="id || undefined">{{ label }}</label>
    <PopoverRoot v-model:open="open">
      <PopoverTrigger
        :id="id || undefined"
        class="model-channel-trigger"
        data-model-channel-trigger
        :aria-label="ariaLabel"
        :disabled="disabled || preferences.saving"
      >
        <span>{{ labelText }}</span
        ><small>{{ channelText }}</small
        ><span aria-hidden="true">⌄</span>
      </PopoverTrigger>
      <PopoverPortal>
        <PopoverContent
          class="generation-model-menu model-channel-menu"
          :side-offset="6"
          align="start"
          @escape-key-down="(event: KeyboardEvent) => event.stopPropagation()"
          @click.stop
        >
          <p class="preference-note">所有项目共用此偏好；仅影响后续生成</p>
          <section v-for="group in groups" :key="group.label">
            <div class="generation-model-group-label">{{ group.label }}</div>
            <div v-for="item in group.items" :key="item.value">
              <div class="model-channel-row">
                <button
                  :disabled="item.disabled || preferences.saving"
                  :aria-pressed="model === item.value"
                  :aria-label="item.label"
                  data-model-option
                  @click="
                    choose(item.value, model === item.value ? selected?.channel || null : null)
                  "
                >
                  {{ model === item.value ? '✓ ' : '' }}{{ item.label }}
                </button>
                <button
                  :disabled="item.disabled || preferences.saving"
                  :aria-label="`${item.label}渠道`"
                  :aria-expanded="expanded === item.value"
                  @click="expand(item.value)"
                >
                  {{ model === item.value ? channelText : '自动（平台推荐）' }} ›
                </button>
              </div>
              <div
                v-if="expanded === item.value"
                class="channel-options"
                :aria-label="`${item.label}可选渠道`"
              >
                <p v-if="channelLoading" role="status">正在读取渠道…</p>
                <p v-else-if="channelError" role="alert">渠道读取失败，请重试；原选择未改变</p>
                <template v-else>
                  <button :disabled="preferences.saving" @click="choose(item.value, null)">
                    自动（平台推荐）
                  </button>
                  <button
                    v-for="channel in preferences.channels[item.value] || []"
                    :key="channel.channel"
                    :disabled="preferences.saving"
                    :aria-pressed="model === item.value && selected?.channel === channel.channel"
                    @click="choose(item.value, channel.channel)"
                  >
                    {{ channel.name }}
                  </button>
                </template>
              </div>
            </div>
          </section>
        </PopoverContent>
      </PopoverPortal>
    </PopoverRoot>
  </div>
</template>
<style scoped>
.model-channel-field {
  width: 100%;
  min-width: 0;
}
.model-channel-trigger,
.model-channel-row button,
.channel-options button {
  font: inherit;
  color: var(--text);
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 8px 10px;
  cursor: pointer;
}
.model-channel-trigger {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  text-align: left;
}
.model-channel-trigger small {
  margin-left: auto;
  color: var(--text-secondary);
}
.model-channel-row {
  display: flex;
  gap: 4px;
  margin: 4px 0;
}
.model-channel-row button:first-child {
  flex: 1;
  text-align: left;
}
.model-channel-menu {
  max-width: min(540px, calc(100vw - 24px));
  width: max(var(--reka-popover-trigger-width), 320px);
  max-height: min(440px, var(--reka-popover-content-available-height));
  overscroll-behavior: contain;
  overflow-y: auto;
}
.channel-options {
  display: flex;
  flex-direction: column;
  margin: 4px 0 8px 24px;
  gap: 4px;
}
.preference-note {
  color: var(--text-secondary);
  font-size: var(--font-sm);
}
button:hover,
button[aria-pressed='true'] {
  background: var(--primary-light);
}
button:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}
</style>
