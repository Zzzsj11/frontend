<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { listPrompts, type PromptTemplateRow } from '../api/adminPrompts'
import AdminPromptDetail from './AdminPromptDetail.vue'

const props = withDefaults(defineProps<{ reloadToken?: number }>(), { reloadToken: 0 })

const rows = ref<PromptTemplateRow[]>([]),
  loading = ref(false),
  error = ref(''),
  selectedKey = ref('')

const loadList = async () => {
  loading.value = true
  error.value = ''
  try {
    rows.value = await listPrompts()
    if (!selectedKey.value && rows.value.length) selectedKey.value = rows.value[0].key
  } catch (e) {
    error.value = e instanceof Error ? e.message : '加载失败'
  } finally {
    loading.value = false
  }
}

const select = (key: string) => {
  selectedKey.value = key
}

watch(
  () => props.reloadToken,
  () => void loadList(),
)
onMounted(loadList)
</script>
<template>
  <div class="prompts-panel">
    <div class="list-pane">
      <p v-if="error" class="error">{{ error }}</p>
      <p v-if="loading" class="muted">加载中…</p>
      <table v-else>
        <thead>
          <tr>
            <th>提示词</th>
            <th>当前版本</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="row in rows"
            :key="row.key"
            :class="{ selected: row.key === selectedKey }"
            @click="select(row.key)"
          >
            <td>
              <b>{{ row.name }}</b>
              <span class="key">{{ row.key }}</span>
            </td>
            <td>
              <span v-if="row.currentVersion" class="badge published">
                v{{ row.currentVersion.version }} 已发布
              </span>
              <span v-else class="badge draft">未发布</span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <AdminPromptDetail
      v-if="selectedKey"
      :key="selectedKey"
      :prompt-key="selectedKey"
      @changed="loadList"
    />
    <p v-else-if="!loading" class="muted placeholder">请选择左侧提示词模板</p>
  </div>
</template>
<style scoped>
.prompts-panel {
  display: grid;
  grid-template-columns: minmax(320px, 420px) 1fr;
  gap: 16px;
  align-items: start;
}
.list-pane {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  overflow: auto;
  max-height: calc(100vh - 180px);
}
table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--font-md);
}
th,
td {
  text-align: left;
  padding: 10px 12px;
  border-bottom: 1px solid var(--border);
}
th {
  color: var(--text-secondary);
  font-weight: 500;
  font-size: var(--font-sm);
}
tbody tr {
  cursor: pointer;
}
tbody tr:hover {
  background: var(--surface-muted);
}
tbody tr.selected {
  background: var(--primary-light);
}
td b {
  display: block;
  font-weight: 600;
}
.key {
  display: block;
  color: var(--text-secondary);
  font-size: var(--font-sm);
  font-family: monospace;
}
.badge {
  display: inline-block;
  padding: 2px 8px;
  border-radius: var(--radius-pill);
  font-size: var(--font-sm);
  white-space: nowrap;
}
.badge.published {
  background: var(--success-light);
  color: var(--success);
}
.badge.draft {
  background: var(--warning-light);
  color: var(--warning);
}
.muted {
  color: var(--text-secondary);
  padding: 12px;
}
.error {
  color: var(--danger);
  padding: 12px;
}
.placeholder {
  padding: 40px;
  text-align: center;
}
</style>
