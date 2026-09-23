<script setup lang="ts">
import { computed, ref } from 'vue'
import { useControl, type Model } from '../stores/control'
import { modelCategory, modelCompany } from '../utils/modelGroups'
const store = useControl()
const category = ref('text')
const search = ref('')
const categories = computed(() => {
  const items = [
    { id: 'text', label: '文本', icon: 'Aa' },
    { id: 'image', label: '图像', icon: '▧' },
    { id: 'video', label: '视频', icon: '▷' },
  ]
  if (store.models.some((m) => modelCategory(m.kind) === 'other'))
    items.push({ id: 'other', label: '其他', icon: '⋯' })
  return items.map((item) => ({
    ...item,
    count: store.models.filter((m) => modelCategory(m.kind) === item.id).length,
  }))
})
const groups = computed(() => {
  const result = new Map<string, Model[]>()
  const query = search.value.trim().toLowerCase()
  for (const model of store.models) {
    const company = modelCompany(model)
    if (
      modelCategory(model.kind) !== category.value ||
      !`${model.id} ${company} ${model.channel}`.toLowerCase().includes(query)
    )
      continue
    if (!result.has(company)) result.set(company, [])
    result.get(company)!.push(model)
  }
  return [...result]
    .sort(([a], [b]) => a.localeCompare(b, 'zh-CN'))
    .map(([company, models]) => ({
      company,
      models: models.sort((a, b) => a.id.localeCompare(b.id)),
    }))
})
function changeLimit(model: Model, event: Event) {
  const input = event.target as HTMLInputElement
  if (!input.checkValidity()) {
    input.reportValidity()
    input.value = String(model.concurrency)
    return
  }
  void store.changeModel(model, { concurrency: Number(input.value) })
}
</script>
<template>
  <section class="model-browser" aria-label="模型分类管理">
    <div class="model-toolbar">
      <div class="category-list" role="group" aria-label="模型类型">
        <button
          v-for="item in categories"
          :key="item.id"
          :aria-pressed="category === item.id"
          :class="{ selected: category === item.id }"
          @click="category = item.id"
        >
          <span class="category-icon" aria-hidden="true">{{ item.icon }}</span
          >{{ item.label }}<span class="count">{{ item.count }}</span>
        </button>
      </div>
      <input
        v-model="search"
        type="search"
        aria-label="搜索模型、公司或渠道"
        placeholder="搜索模型、公司或渠道"
      />
    </div>
    <div class="results-summary" aria-live="polite">
      {{ groups.length }} 家公司 ·
      {{ groups.reduce((total, group) => total + group.models.length, 0) }} 个模型
    </div>
    <section
      v-for="group in groups"
      :key="group.company"
      class="company-group card"
      :aria-label="group.company + ' 模型'"
    >
      <div class="company-heading">
        <h3>{{ group.company }}</h3>
        <span>{{ group.models.length }} 个模型</span
        ><span class="enabled-count"
          >已启用 {{ group.models.filter((m) => m.enabled).length }}</span
        >
      </div>
      <div class="model-list">
        <article v-for="model in group.models" :key="model.id" class="model-row">
          <div class="model-identity">
            <strong>{{ model.id }}</strong
            ><span class="channel">接入渠道 · {{ model.channel }}</span>
          </div>
          <label class="limit"
            >并发上限<input
              :aria-label="model.id + ' 并发上限'"
              type="number"
              required
              min="1"
              max="200"
              step="1"
              :value="model.concurrency"
              :disabled="store.loading"
              @change="changeLimit(model, $event)"
          /></label>
          <button
            class="status-button"
            :class="{ enabled: model.enabled }"
            :aria-label="model.id + (model.enabled ? ' 停用模型' : ' 启用模型')"
            :disabled="store.loading"
            @click="store.changeModel(model, { enabled: !model.enabled })"
          >
            <span aria-hidden="true">●</span>{{ model.enabled ? '已启用' : '已停用' }}
          </button>
          <details class="capabilities">
            <summary>能力配置</summary>
            <pre>{{ JSON.stringify(model.capabilities, null, 2) }}</pre>
          </details>
        </article>
      </div>
    </section>
    <div v-if="!groups.length" class="card empty">
      <h3>{{ search ? '未找到匹配的模型' : '该类型暂无模型' }}</h3>
      <button v-if="search" class="secondary" @click="search = ''">清除搜索</button>
    </div>
  </section>
</template>
<style scoped>
.model-browser {
  display: grid;
  gap: 18px;
}
.model-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  flex-wrap: wrap;
}
.category-list {
  display: flex;
  gap: 6px;
  padding: 5px;
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
}
.category-list button {
  display: flex;
  align-items: center;
  gap: 12px;
  background: transparent;
  color: var(--muted);
}
.category-list button.selected {
  background: var(--primary-light);
  color: var(--primary);
}
.category-icon {
  font-weight: 700;
}
.count {
  font-size: 12px;
  border-radius: var(--radius-sm);
  background: var(--bg);
  padding: 2px 7px;
}
.model-toolbar input {
  width: min(100%, 300px);
  margin: 0;
}
.results-summary {
  color: var(--muted);
  font-size: 13px;
}
.company-group {
  padding: 0;
  overflow: hidden;
}
.company-heading {
  display: flex;
  gap: 12px;
  align-items: center;
  padding: 18px 24px;
  background: var(--bg);
  border-bottom: 1px solid var(--border);
}
.company-heading h3 {
  margin: 0;
  font-size: 17px;
}
.company-heading span {
  font-size: 12px;
  color: var(--muted);
}
.enabled-count {
  margin-left: auto;
}
.model-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 100px 112px;
  gap: 12px 24px;
  align-items: center;
  padding: 20px 24px;
  border-bottom: 1px solid var(--border);
}
.model-row:last-child {
  border-bottom: 0;
}
.model-identity {
  display: grid;
  gap: 8px;
  min-width: 0;
}
.model-identity strong {
  font-size: 15px;
  overflow-wrap: anywhere;
}
.channel,
.limit {
  font-size: 12px;
  color: var(--muted);
}
.limit input {
  width: 100%;
  color: var(--text);
}
.status-button {
  background: var(--bg);
  color: var(--muted);
  border-color: var(--border);
  font-size: 13px;
}
.status-button span {
  margin-right: 7px;
}
.status-button.enabled {
  background: var(--primary-light);
  color: var(--primary);
}
.capabilities {
  grid-column: 1 / -1;
  font-size: 12px;
}
.capabilities summary {
  cursor: pointer;
  color: var(--primary);
  width: fit-content;
}
.capabilities pre {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  padding: 16px;
  background: var(--bg);
  border-radius: var(--radius-sm);
  max-height: 320px;
  overflow: auto;
}
.empty {
  text-align: center;
}
@media (max-width: 600px) {
  .category-list {
    width: 100%;
    flex-wrap: wrap;
  }
  .category-list button {
    flex: 1;
    justify-content: center;
    gap: 7px;
    padding: 10px;
  }
  .model-toolbar input {
    width: 100%;
  }
  .model-row {
    grid-template-columns: 1fr 112px;
    padding: 18px;
    gap: 14px;
  }
  .model-identity {
    grid-column: 1 / -1;
  }
  .limit {
    display: flex;
    align-items: center;
    gap: 10px;
  }
  .limit input {
    width: 72px;
    margin: 0;
  }
  .company-heading {
    padding: 16px 18px;
  }
}
</style>
