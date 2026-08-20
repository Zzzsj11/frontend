<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import {
  createStoryboardOption,
  deleteStoryboardOption,
  listStoryboardOptions,
  updateStoryboardOption,
  type StoryboardOptionItem,
  type StoryboardOptionKind,
} from '../api/adminStoryboardOptions'
import AppIcon from './AppIcon.vue'

const kinds: [StoryboardOptionKind, string][] = [
  ['genre', '曲风分类'],
  ['season', '季节'],
  ['age_group', '年龄段'],
  ['visual_style', '画面风格'],
]

const kind = ref<StoryboardOptionKind>('genre')
const items = ref<StoryboardOptionItem[]>([])
const loading = ref(false)
const error = ref('')
/** 操作进行中（防重复提交） */
const busy = ref(false)

const kindLabel = computed(() => kinds.find(([value]) => value === kind.value)?.[1] ?? '')

const load = async () => {
  loading.value = true
  error.value = ''
  try {
    items.value = await listStoryboardOptions(kind.value)
  } catch (e) {
    error.value = e instanceof Error ? e.message : '加载失败'
  } finally {
    loading.value = false
  }
}
watch(kind, () => {
  cancelEdit()
  cancelAdd()
  confirmingId.value = ''
  void load()
})
onMounted(load)

/** 展示行：genre 按 parentId 组树后深度优先拍平（带 depth 缩进）；其他 kind 同级平铺 */
interface OptionRow {
  item: StoryboardOptionItem
  depth: number
}
const rows = computed<OptionRow[]>(() => {
  const byParent = new Map<string | null, StoryboardOptionItem[]>()
  for (const item of items.value) {
    const list = byParent.get(item.parentId) ?? []
    list.push(item)
    byParent.set(item.parentId, list)
  }
  for (const list of byParent.values()) list.sort((a, b) => a.sortOrder - b.sortOrder)
  const out: OptionRow[] = []
  const walk = (parentId: string | null, depth: number) => {
    for (const item of byParent.get(parentId) ?? []) {
      out.push({ item, depth })
      walk(item.id, depth + 1)
    }
  }
  walk(null, 0)
  return out
})

/** 同级兄弟（排序后），用于上移/下移 */
const siblingsOf = (item: StoryboardOptionItem) =>
  rows.value.filter((row) => row.item.parentId === item.parentId).map((row) => row.item)

// ---------- 重命名（行内编辑） ----------
const editingId = ref('')
const editingName = ref('')
const startEdit = (item: StoryboardOptionItem) => {
  cancelAdd()
  confirmingId.value = ''
  editingId.value = item.id
  editingName.value = item.name
}
const cancelEdit = () => {
  editingId.value = ''
  editingName.value = ''
}
const submitEdit = async (item: StoryboardOptionItem) => {
  const name = editingName.value.trim()
  if (!name || name === item.name) return cancelEdit()
  busy.value = true
  error.value = ''
  try {
    await updateStoryboardOption(item.id, { name })
    cancelEdit()
    await load()
  } catch (e) {
    error.value = e instanceof Error ? e.message : '保存失败'
  } finally {
    busy.value = false
  }
}

// ---------- 新增（行内表单；addingUnder: null=根级，string=父节点 id） ----------
const addingUnder = ref<string | null | undefined>(undefined)
const addingName = ref('')
const startAdd = (parentId: string | null) => {
  cancelEdit()
  confirmingId.value = ''
  addingUnder.value = parentId
  addingName.value = ''
}
const cancelAdd = () => {
  addingUnder.value = undefined
  addingName.value = ''
}
const submitAdd = async () => {
  const name = addingName.value.trim()
  if (!name) return
  busy.value = true
  error.value = ''
  try {
    await createStoryboardOption({ kind: kind.value, parentId: addingUnder.value ?? null, name })
    cancelAdd()
    await load()
  } catch (e) {
    error.value = e instanceof Error ? e.message : '新增失败'
  } finally {
    busy.value = false
  }
}

// ---------- 删除（二次确认；genre 级联子孙由后端处理） ----------
const confirmingId = ref('')
const removeItem = async (item: StoryboardOptionItem) => {
  busy.value = true
  error.value = ''
  try {
    await deleteStoryboardOption(item.id)
    confirmingId.value = ''
    await load()
  } catch (e) {
    error.value = e instanceof Error ? e.message : '删除失败'
  } finally {
    busy.value = false
  }
}

// ---------- 排序：与相邻兄弟交换 sortOrder ----------
const moveItem = async (item: StoryboardOptionItem, delta: -1 | 1) => {
  const siblings = siblingsOf(item)
  const index = siblings.findIndex((x) => x.id === item.id)
  const other = siblings[index + delta]
  if (!other || busy.value) return
  busy.value = true
  error.value = ''
  try {
    await updateStoryboardOption(item.id, { sortOrder: other.sortOrder })
    await updateStoryboardOption(other.id, { sortOrder: item.sortOrder })
    await load()
  } catch (e) {
    error.value = e instanceof Error ? e.message : '排序失败'
  } finally {
    busy.value = false
  }
}
const isFirst = (item: StoryboardOptionItem) => siblingsOf(item)[0]?.id === item.id
const isLast = (item: StoryboardOptionItem) => siblingsOf(item).at(-1)?.id === item.id
const updateCastPolicy = async (item: StoryboardOptionItem, event: Event) => {
  const value = (event.target as HTMLSelectElement).value
  busy.value = true
  error.value = ''
  try {
    await updateStoryboardOption(item.id, {
      castPolicy: value ? (value as 'required' | 'optional_random') : null,
    })
    await load()
  } catch (e) {
    error.value = e instanceof Error ? e.message : '人物策略保存失败'
  } finally {
    busy.value = false
  }
}
/** 新增位置标签：根级或具体父分类名 */
const addingUnderName = computed(() => {
  if (addingUnder.value === undefined) return ''
  if (addingUnder.value === null) return kindLabel.value
  return items.value.find((x) => x.id === addingUnder.value)?.name ?? ''
})
</script>

<template>
  <div class="options-panel">
    <div class="kind-tabs">
      <button
        v-for="[value, label] in kinds"
        :key="value"
        class="kind-tab"
        :class="{ on: kind === value }"
        @click="kind = value"
      >
        {{ label }}
      </button>
      <button class="add-root" :disabled="busy" @click="startAdd(null)">
        <AppIcon name="plus" :size="14" /> 新增{{ kindLabel }}
      </button>
    </div>

    <p v-if="error" class="error">{{ error }}</p>

    <!-- 行内新增表单 -->
    <div v-if="addingUnder !== undefined" class="inline-form">
      <span class="form-label">新增到「{{ addingUnderName }}」：</span>
      <input
        v-model="addingName"
        class="name-input"
        :placeholder="`请输入${kindLabel}名称`"
        maxlength="60"
        @keyup.enter="submitAdd"
        @keyup.esc="cancelAdd"
      />
      <button class="op-btn primary" :disabled="busy || !addingName.trim()" @click="submitAdd">
        <AppIcon name="check" :size="13" /> 保存
      </button>
      <button class="op-btn" :disabled="busy" @click="cancelAdd">
        <AppIcon name="close" :size="13" /> 取消
      </button>
    </div>

    <p v-if="loading" class="muted">加载中…</p>
    <table v-else class="options-table">
      <thead>
        <tr>
          <th>名称</th>
          <th v-if="kind === 'genre'">人物选择策略</th>
          <th class="ops-col">操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="row.item.id">
          <td>
            <span class="name-cell" :style="{ paddingLeft: `${row.depth * 22}px` }">
              <span v-if="row.depth > 0" class="depth-mark">└</span>
              <template v-if="editingId === row.item.id">
                <input
                  v-model="editingName"
                  class="name-input"
                  maxlength="60"
                  @keyup.enter="submitEdit(row.item)"
                  @keyup.esc="cancelEdit"
                />
                <button class="op-btn primary" :disabled="busy" @click="submitEdit(row.item)">
                  <AppIcon name="check" :size="13" />
                </button>
                <button class="op-btn" :disabled="busy" @click="cancelEdit">
                  <AppIcon name="close" :size="13" />
                </button>
              </template>
              <template v-else>{{ row.item.name }}</template>
            </span>
          </td>
          <td v-if="kind === 'genre'">
            <select
              class="policy-select"
              :value="row.item.castPolicy ?? ''"
              :disabled="busy"
              :aria-label="`${row.item.name}人物选择策略`"
              @change="updateCastPolicy(row.item, $event)"
            >
              <option value="">继承上级（默认自动匹配）</option>
              <option value="required">必须手动选择</option>
              <option value="optional_random">可选，未选自动匹配</option>
            </select>
          </td>
          <td class="ops-col">
            <template v-if="confirmingId === row.item.id">
              <span class="danger-text"
                >确认删除{{ row.depth < 2 && kind === 'genre' ? '（含子级）' : '' }}？</span
              >
              <button class="op-btn danger" :disabled="busy" @click="removeItem(row.item)">
                确认
              </button>
              <button class="op-btn" :disabled="busy" @click="confirmingId = ''">取消</button>
            </template>
            <template v-else>
              <button class="op-btn" title="重命名" :disabled="busy" @click="startEdit(row.item)">
                <AppIcon name="edit" :size="13" />
              </button>
              <button
                v-if="kind === 'genre' && row.depth < 2"
                class="op-btn"
                title="新增子级"
                :disabled="busy"
                @click="startAdd(row.item.id)"
              >
                <AppIcon name="plus" :size="13" />
              </button>
              <button
                class="op-btn text"
                :disabled="busy || isFirst(row.item)"
                @click="moveItem(row.item, -1)"
              >
                上移
              </button>
              <button
                class="op-btn text"
                :disabled="busy || isLast(row.item)"
                @click="moveItem(row.item, 1)"
              >
                下移
              </button>
              <button
                class="op-btn"
                title="删除"
                :disabled="busy"
                @click="confirmingId = row.item.id"
              >
                <AppIcon name="trash" :size="13" />
              </button>
            </template>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="kind === 'genre' ? 3 : 2" class="muted">
            暂无选项，点击右上角「新增{{ kindLabel }}」
          </td>
        </tr>
      </tbody>
    </table>
    <p class="hint">已生成项目保存的是分类中文名，此处增删改不影响历史项目。</p>
  </div>
</template>

<style scoped>
.options-panel {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  padding: 20px;
  box-shadow: var(--shadow-card);
}
.kind-tabs {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}
.kind-tab {
  border: 1px solid var(--border-dark);
  background: var(--surface);
  border-radius: var(--radius-pill);
  padding: 6px 14px;
  font-size: var(--font-md);
  color: var(--text-secondary);
  cursor: pointer;
  transition:
    border-color 0.15s,
    color 0.15s,
    background 0.15s;
}
.kind-tab:hover:not(.on) {
  color: var(--primary);
  border-color: var(--primary);
}
.kind-tab.on {
  border-color: var(--primary);
  color: var(--primary);
  background: var(--primary-light);
  font-weight: 600;
}
.add-root {
  margin-left: auto;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  border: 1px solid var(--primary);
  background: var(--primary);
  color: #fff;
  border-radius: var(--radius-sm);
  padding: 6px 12px;
  font-size: var(--font-md);
  cursor: pointer;
}
.add-root:hover:not(:disabled) {
  background: var(--primary-hover);
}
.add-root:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.inline-form {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 12px;
  margin-bottom: 12px;
  border: 1px dashed var(--primary);
  border-radius: var(--radius-sm);
  background: var(--primary-light);
}
.form-label {
  font-size: var(--font-md);
  color: var(--text);
  white-space: nowrap;
}
.name-input {
  border: 1px solid var(--border-dark);
  border-radius: var(--radius-sm);
  padding: 6px 10px;
  font-size: var(--font-md);
  min-width: 180px;
}
.name-input:focus {
  outline: none;
  border-color: var(--primary);
}
.policy-select {
  min-width: 190px;
  padding: 6px 8px;
  border: 1px solid var(--border-dark);
  border-radius: var(--radius-sm);
  background: var(--surface);
  color: var(--text);
}
.options-table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--font-md);
}
th,
td {
  text-align: left;
  padding: 8px 12px;
  border-bottom: 1px solid var(--border);
}
th {
  color: var(--text-secondary);
  font-weight: 600;
  font-size: var(--font-sm);
}
.name-cell {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.depth-mark {
  color: var(--text-secondary);
}
.ops-col {
  width: 320px;
  white-space: nowrap;
}
.op-btn {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  border: 1px solid var(--border-dark);
  background: var(--surface);
  border-radius: var(--radius-sm);
  padding: 4px 8px;
  margin-right: 6px;
  font-size: var(--font-sm);
  color: var(--text-secondary);
  cursor: pointer;
  transition:
    border-color 0.15s,
    color 0.15s,
    background 0.15s;
}
.op-btn:hover:not(:disabled) {
  color: var(--primary);
  border-color: var(--primary);
  background: var(--primary-light);
}
.op-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
.op-btn.primary {
  color: var(--primary);
  border-color: var(--primary);
}
.op-btn.danger {
  color: var(--danger);
  border-color: var(--danger-border);
}
.op-btn.danger:hover:not(:disabled) {
  color: var(--danger);
  border-color: var(--danger);
  background: var(--danger-light);
}
.danger-text {
  color: var(--danger);
  font-size: var(--font-sm);
  margin-right: 8px;
}
.muted {
  color: var(--text-secondary);
  padding: 12px;
}
.error {
  color: var(--danger);
  margin: 0 0 12px;
}
.hint {
  margin: 12px 0 0;
  color: var(--text-secondary);
  font-size: var(--font-sm);
}
</style>
