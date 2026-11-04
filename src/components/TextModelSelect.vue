<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { apiRequest } from '../api/client'
import { useGenerationPreferences } from '../stores/generationPreferences'
import GenerationModelSelect from './GenerationModelSelect.vue'
const preferences = useGenerationPreferences()
const models = ref<Array<{ id: string; name: string }>>([])
const groups = computed(() => [
  {
    label: '文本模型',
    items: models.value.map((model) => ({
      value: model.id,
      label: model.name.replace('（all in one）', ''),
    })),
  },
])
onMounted(async () => {
  try {
    models.value = await apiRequest('/model-options?modality=chat')
  } catch {
    /* API 客户端统一展示目录错误。 */
  }
})
</script>
<template>
  <GenerationModelSelect
    :model-value="preferences.selections.text?.model || 'gemini-3.8-flash-all-in-one'"
    modality="text"
    :groups="groups"
    aria-label="文本模型"
  />
</template>
