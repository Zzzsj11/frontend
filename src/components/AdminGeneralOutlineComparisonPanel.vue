<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import {
  fetchChatComparisonModels,
  runGeneralOutlineComparison,
  type ChatComparisonModel,
  type GeneralOutlineComparisonResult,
} from '../api/adminChatComparison'
import AdminGeneralOutlineResults from './AdminGeneralOutlineResults.vue'

const models = ref<ChatComparisonModel[]>([])
const selectedModels = ref(['gpt-5.5', 'gpt-5.6-sol', 'claude-opus-4-8'])
const loading = ref(false)
const error = ref('')
const results = ref<GeneralOutlineComparisonResult[]>([])
const form = reactive({
  genre: '流行抒情',
  secondary_category: '都市情感',
  tertiary_category: '失恋后的释然',
  season: '秋',
  gender: '女',
  age_group: '青年',
  visual_style: '写实电影感，暖冷色温递进',
  empty_shot_count: 4,
  character_shot_count: 17,
  total_duration: 210,
  extra_requirement: '画面克制，强调人物情绪与空间连续性',
  overall_prompt: '同一座临海城市，从黄昏过渡到夜晚，人物造型保持一致。',
  character_name: '林夏',
  character_age: '约25岁',
  character_appearance: '黑色齐肩发，清冷气质',
  character_clothing: '米白风衣与深色长裙',
})

const canRun = computed(
  () => selectedModels.value.length > 0 && form.genre.trim() && !loading.value,
)
const toggleModel = (code: string) => {
  if (selectedModels.value.includes(code))
    selectedModels.value = selectedModels.value.filter((item) => item !== code)
  else if (selectedModels.value.length < 6) selectedModels.value = [...selectedModels.value, code]
  else error.value = '单次最多选择 6 个模型'
}
const run = async () => {
  if (!canRun.value) return
  loading.value = true
  error.value = ''
  results.value = []
  try {
    results.value = (
      await runGeneralOutlineComparison({ ...form, models: selectedModels.value })
    ).results
  } catch (e) {
    error.value = e instanceof Error ? e.message : '通用大纲对比失败'
  } finally {
    loading.value = false
  }
}
onMounted(async () => {
  try {
    models.value = await fetchChatComparisonModels()
  } catch (e) {
    error.value = e instanceof Error ? e.message : '模型列表加载失败'
  }
})
</script>

<template>
  <div class="general-panel">
    <section class="config-card">
      <div class="intro">
        <div>
          <h3>通用 MV 大纲对比</h3>
          <p>复用正式大纲提示词、重试和结构校验；结果仅供测试，不写入任何项目。</p>
        </div>
        <span>已选 {{ selectedModels.length }}/6</span>
      </div>
      <div class="form-grid">
        <label>曲风<input v-model="form.genre" /></label>
        <label>二级分类<input v-model="form.secondary_category" /></label>
        <label>三级分类<input v-model="form.tertiary_category" /></label>
        <label>季节<input v-model="form.season" /></label>
        <label>性别<input v-model="form.gender" /></label>
        <label>年龄段<input v-model="form.age_group" /></label>
        <label
          >空镜数量<input v-model.number="form.empty_shot_count" type="number" min="0" max="30"
        /></label>
        <label
          >人物镜数量<input
            v-model.number="form.character_shot_count"
            type="number"
            min="0"
            max="30"
        /></label>
        <label
          >总时长（秒）<input v-model.number="form.total_duration" type="number" min="1" max="600"
        /></label>
        <label>人物名称<input v-model="form.character_name" /></label>
        <label>人物年龄<input v-model="form.character_age" /></label>
        <label>人物外观<input v-model="form.character_appearance" /></label>
        <label class="wide">人物服装<input v-model="form.character_clothing" /></label>
        <label class="wide">视觉风格<textarea v-model="form.visual_style" rows="2" /></label>
        <label class="wide">额外要求<textarea v-model="form.extra_requirement" rows="2" /></label>
        <label class="wide">整体提示词<textarea v-model="form.overall_prompt" rows="3" /></label>
      </div>
      <fieldset>
        <legend>选择模型</legend>
        <div class="model-grid">
          <button
            v-for="model in models"
            :key="model.code"
            type="button"
            :class="{ selected: selectedModels.includes(model.code) }"
            @click="toggleModel(model.code)"
          >
            <b>{{ model.name }}</b
            ><small>{{ model.code }}</small>
          </button>
        </div>
      </fieldset>
      <div class="actions">
        <button class="run-button" type="button" :disabled="!canRun" @click="run">
          {{ loading ? `正在生成 ${selectedModels.length} 份大纲…` : '开始业务对比' }}
        </button>
      </div>
      <p v-if="error" class="error">{{ error }}</p>
    </section>

    <AdminGeneralOutlineResults v-if="results.length" :results="results" />
  </div>
</template>

<style scoped>
.general-panel {
  display: grid;
  gap: 16px;
}
.config-card {
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: var(--bg);
  padding: 18px;
  box-shadow: var(--shadow-card);
}
.intro,
.actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
h3,
p {
  margin: 0;
}
.intro p,
small {
  color: var(--text-secondary);
  font-size: var(--font-sm);
}
.intro > span {
  border-radius: var(--radius-pill);
  background: var(--primary-light);
  color: var(--primary);
  padding: 5px 10px;
  font-size: var(--font-sm);
}
.form-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
  margin-top: 16px;
}
label {
  display: grid;
  gap: 6px;
  font-size: var(--font-sm);
  font-weight: 600;
}
.wide {
  grid-column: 1/-1;
}
input,
textarea {
  border: 1px solid var(--border-dark);
  border-radius: var(--radius-sm);
  background: var(--bg);
  color: var(--text);
  padding: 9px 10px;
  font: inherit;
}
textarea {
  resize: vertical;
}
fieldset {
  margin-top: 16px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 12px;
}
.model-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(170px, 1fr));
  gap: 8px;
}
.model-grid button {
  display: grid;
  gap: 3px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--bg);
  padding: 9px;
  color: var(--text);
  text-align: left;
  cursor: pointer;
}
.model-grid button:hover,
.model-grid button.selected {
  border-color: var(--primary);
}
.model-grid button.selected {
  background: var(--primary-light);
}
.actions {
  justify-content: flex-end;
  margin-top: 14px;
}
.run-button {
  border: 0;
  border-radius: var(--radius-sm);
  background: var(--primary);
  color: white;
  padding: 10px 18px;
  cursor: pointer;
}
.run-button:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}
.error {
  color: var(--danger);
}
@media (max-width: 760px) {
  .form-grid {
    grid-template-columns: 1fr;
  }
  .wide {
    grid-column: auto;
  }
}
</style>
