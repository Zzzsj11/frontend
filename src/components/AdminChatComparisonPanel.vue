<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import {
  fetchChatComparisonModels,
  runChatComparison,
  type ChatComparisonModel,
  type ChatComparisonResult,
} from '../api/adminChatComparison'
import AdminChatComparisonResults from './AdminChatComparisonResults.vue'

const models = ref<ChatComparisonModel[]>([])
const selectedModels = ref<string[]>(['gpt-5.5', 'gpt-5.6-sol', 'claude-opus-4-8'])
const systemPrompt = ref('你是一个专业、严谨的人工智能助手。')
const prompt = ref('')
const temperature = ref(0.2)
const maxTokens = ref(2048)
const loading = ref(false)
const loadingModels = ref(false)
const error = ref('')
const results = ref<ChatComparisonResult[]>([])

const canRun = computed(
  () => prompt.value.trim().length > 0 && selectedModels.value.length > 0 && !loading.value,
)
const groupedModels = computed(() => ({
  openai: models.value.filter((item) => item.protocol === 'openai'),
  anthropic: models.value.filter((item) => item.protocol === 'anthropic'),
}))

const loadModels = async () => {
  loadingModels.value = true
  error.value = ''
  try {
    models.value = await fetchChatComparisonModels()
    const allowed = new Set(models.value.map((item) => item.code))
    selectedModels.value = selectedModels.value.filter((item) => allowed.has(item)).slice(0, 6)
  } catch (e) {
    error.value = e instanceof Error ? e.message : '模型列表加载失败'
  } finally {
    loadingModels.value = false
  }
}

const toggleModel = (code: string) => {
  if (selectedModels.value.includes(code)) {
    selectedModels.value = selectedModels.value.filter((item) => item !== code)
    return
  }
  if (selectedModels.value.length >= 6) {
    error.value = '单次最多选择 6 个模型'
    return
  }
  error.value = ''
  selectedModels.value = [...selectedModels.value, code]
}

const run = async () => {
  if (!canRun.value) return
  loading.value = true
  error.value = ''
  results.value = []
  try {
    const response = await runChatComparison({
      systemPrompt: systemPrompt.value.trim(),
      prompt: prompt.value.trim(),
      models: selectedModels.value,
      temperature: temperature.value,
      maxTokens: maxTokens.value,
    })
    results.value = response.results
  } catch (e) {
    error.value = e instanceof Error ? e.message : '模型对比请求失败'
  } finally {
    loading.value = false
  }
}

onMounted(loadModels)
</script>

<template>
  <div class="comparison-panel">
    <section class="config-card">
      <div class="intro">
        <div>
          <h3>同提示词多模型对比</h3>
          <p>仅执行独立测试，不会修改项目主流程的默认模型 GPT 5.5。</p>
        </div>
        <span class="selection-count">已选 {{ selectedModels.length }}/6</span>
      </div>

      <label class="field">
        <span>系统提示词</span>
        <textarea v-model="systemPrompt" rows="3" maxlength="12000" />
      </label>
      <label class="field">
        <span>用户提示词</span>
        <textarea
          v-model="prompt"
          rows="7"
          maxlength="30000"
          placeholder="输入需要同时发送给多个模型的提示词…"
        />
      </label>

      <fieldset class="model-picker" :disabled="loadingModels || loading">
        <legend>选择模型</legend>
        <div class="model-group">
          <b>OpenAI 兼容协议</b>
          <div class="model-grid">
            <button
              v-for="model in groupedModels.openai"
              :key="model.code"
              type="button"
              class="model-option"
              :class="{ selected: selectedModels.includes(model.code) }"
              :aria-pressed="selectedModels.includes(model.code)"
              @click="toggleModel(model.code)"
            >
              <span>{{ model.name }}</span
              ><small>{{ model.code }}</small>
            </button>
          </div>
        </div>
        <div class="model-group">
          <b>Anthropic Messages 协议</b>
          <div class="model-grid">
            <button
              v-for="model in groupedModels.anthropic"
              :key="model.code"
              type="button"
              class="model-option"
              :class="{ selected: selectedModels.includes(model.code) }"
              :aria-pressed="selectedModels.includes(model.code)"
              @click="toggleModel(model.code)"
            >
              <span>{{ model.name }}</span
              ><small>{{ model.code }}</small>
            </button>
          </div>
        </div>
      </fieldset>

      <div class="actions">
        <label
          >Temperature <input v-model.number="temperature" type="number" min="0" max="2" step="0.1"
        /></label>
        <label
          >最大 Token <input v-model.number="maxTokens" type="number" min="1" max="8192"
        /></label>
        <button type="button" class="run-button" :disabled="!canRun" @click="run">
          {{ loading ? `正在请求 ${selectedModels.length} 个模型…` : '开始对比' }}
        </button>
      </div>
      <p v-if="error" class="error-message">{{ error }}</p>
    </section>

    <AdminChatComparisonResults v-if="results.length" :results="results" />
  </div>
</template>

<style scoped>
.comparison-panel {
  display: grid;
  gap: 18px;
}
.config-card {
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: var(--bg);
  box-shadow: var(--shadow-card);
}
.config-card {
  padding: 20px;
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
.selection-count {
  border-radius: var(--radius-pill);
  padding: 5px 10px;
  background: var(--primary-light);
  color: var(--primary);
  font-size: var(--font-sm);
}
.field {
  display: grid;
  gap: 7px;
  margin-top: 16px;
  font-weight: 600;
}
textarea,
input {
  border: 1px solid var(--border-dark);
  border-radius: var(--radius-sm);
  background: var(--bg);
  color: var(--text);
  font: inherit;
}
textarea {
  resize: vertical;
  padding: 10px 12px;
  line-height: 1.6;
}
textarea:focus,
input:focus {
  border-color: var(--primary);
  outline: none;
}
.model-picker {
  margin-top: 16px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 14px;
}
.model-group + .model-group {
  margin-top: 14px;
}
.model-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 8px;
  margin-top: 8px;
}
.model-option {
  display: grid;
  gap: 3px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--bg);
  padding: 10px;
  color: var(--text);
  text-align: left;
  cursor: pointer;
}
.model-option:hover {
  border-color: var(--primary);
}
.model-option.selected {
  border-color: var(--primary);
  background: var(--primary-light);
}
.actions {
  justify-content: flex-end;
  margin-top: 16px;
  flex-wrap: wrap;
}
.actions label {
  display: flex;
  align-items: center;
  gap: 7px;
  font-size: var(--font-sm);
}
.actions input {
  width: 88px;
  padding: 8px;
}
.run-button {
  border: 0;
  border-radius: var(--radius-sm);
  background: var(--primary);
  padding: 10px 18px;
  color: white;
  cursor: pointer;
}
.run-button:disabled {
  cursor: not-allowed;
  opacity: 0.55;
}
.error-message {
  margin-top: 12px;
  color: var(--danger);
}
@media (max-width: 720px) {
  .config-card {
    padding: 14px;
  }
}
</style>
