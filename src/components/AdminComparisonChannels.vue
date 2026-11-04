<script setup lang="ts">
import { ref, watch } from 'vue'
import BaseSelect from './base/BaseSelect.vue'
import { apiRequest } from '../api/client'
import type { GenerationChannel } from '../stores/generationPreferences'
const props = defineProps<{
  models: Array<{ code: string; name: string }>
  modelValue: Record<string, string | null>
  disabled: boolean
}>()
const emit = defineEmits<{ 'update:modelValue': [value: Record<string, string | null>] }>()
const catalogs = ref<Record<string, GenerationChannel[]>>({})
const errors = ref<Record<string, boolean>>({})
const loading = ref<Record<string, boolean>>({})
async function load(code: string) {
  if (loading.value[code]) return
  loading.value[code] = true
  errors.value[code] = false
  try {
    const result = await apiRequest<{ channels: GenerationChannel[] }>(
      `/admin/chat-comparison/models/${encodeURIComponent(code)}/channels`,
    )
    catalogs.value[code] = result.channels.filter((item) => item.available)
  } catch {
    errors.value[code] = true
  } finally {
    loading.value[code] = false
  }
}
watch(
  () => props.models,
  (models) => {
    for (const model of models) {
      if (model.code.endsWith('-all-in-one') && !catalogs.value[model.code]) void load(model.code)
    }
  },
  { immediate: true },
)
function select(code: string, value: string | number) {
  emit('update:modelValue', { ...props.modelValue, [code]: String(value) || null })
}
</script>
<template>
  <div class="comparison-channels">
    <template v-for="model in models" :key="model.code">
      <label v-if="model.code.endsWith('-all-in-one')">
        <span>{{ model.name }}渠道</span>
        <BaseSelect
          :model-value="modelValue[model.code] || ''"
          :aria-label="`${model.name}渠道`"
          :disabled="disabled || loading[model.code]"
          @update:model-value="select(model.code, $event)"
        >
          <option value="">自动（平台推荐）</option>
          <option
            v-if="
              modelValue[model.code] &&
              !catalogs[model.code]?.some((c) => c.channel === modelValue[model.code])
            "
            :value="modelValue[model.code] || ''"
            disabled
          >
            {{ modelValue[model.code] }}（待确认）
          </option>
          <option
            v-for="channel in catalogs[model.code] || []"
            :key="channel.channel"
            :value="channel.channel"
          >
            {{ channel.name }}
          </option>
        </BaseSelect>
        <button
          v-if="errors[model.code]"
          type="button"
          :disabled="disabled"
          @click="load(model.code)"
        >
          重试渠道目录（原选择保留）
        </button>
      </label>
    </template>
  </div>
</template>
<style scoped>
.comparison-channels {
  display: grid;
  gap: 12px;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
}
label {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
</style>
