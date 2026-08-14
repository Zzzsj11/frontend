<script setup lang="ts">
import { onMounted, ref } from 'vue'
import {
  createPromptDraft,
  deletePromptDraft,
  getPromptDetail,
  publishPrompt,
  type PromptDetail,
} from '../api/adminPrompts'
import { confirmDialog } from '../composables/useConfirmDialog'
import AdminPromptPreview from './AdminPromptPreview.vue'

const props = defineProps<{ promptKey: string }>()
const emit = defineEmits<{ changed: [] }>()

const detail = ref<PromptDetail | null>(null),
  loading = ref(false),
  busy = ref(false),
  error = ref(''),
  notice = ref(''),
  editorContent = ref(''),
  changeNote = ref('')

const statusText: Record<string, string> = {
  draft: '草稿',
  published: '已发布',
  archived: '已归档',
}

const load = async () => {
  loading.value = true
  error.value = ''
  try {
    detail.value = await getPromptDetail(props.promptKey)
    const current = detail.value.versions.find((v) => v.id === detail.value?.currentVersionId)
    editorContent.value = current?.content ?? detail.value.defaultContent ?? ''
  } catch (e) {
    error.value = e instanceof Error ? e.message : '加载失败'
  } finally {
    loading.value = false
  }
}

/** 把指定版本内容载入编辑区（查看历史 / 以旧版本为底改新版本） */
const viewVersion = (content: string) => {
  editorContent.value = content
  notice.value = '已载入所选版本内容到编辑区，修改后请存为新草稿'
}

const resetDefault = () => {
  if (detail.value?.defaultContent != null) viewVersion(detail.value.defaultContent)
}

/** 统一执行写操作：成功后刷新详情并通知列表刷新版本摘要 */
const run = async (action: () => Promise<string>) => {
  busy.value = true
  error.value = ''
  notice.value = ''
  try {
    notice.value = await action()
    await load()
    emit('changed')
  } catch (e) {
    error.value = e instanceof Error ? e.message : '操作失败'
  } finally {
    busy.value = false
  }
}

const saveDraft = () =>
  run(async () => {
    const created = await createPromptDraft(props.promptKey, editorContent.value, changeNote.value)
    changeNote.value = ''
    return `已存为草稿 v${created.version}（发布后才对生成链路生效）`
  })

const publish = async (versionId: string, version: number) => {
  const ok = await confirmDialog({
    title: '发布提示词',
    message: `发布后生成链路立即切换到 v${version}，旧版本自动归档。确认发布？`,
    confirmText: '发布',
  })
  if (!ok) return
  await run(async () => {
    await publishPrompt(props.promptKey, versionId)
    return `v${version} 已发布`
  })
}

const removeDraft = async (versionId: string, version: number) => {
  const ok = await confirmDialog({
    message: `确认删除草稿 v${version}？此操作不可恢复。`,
    confirmText: '删除',
    danger: true,
  })
  if (!ok) return
  await run(async () => {
    await deletePromptDraft(props.promptKey, versionId)
    return `草稿 v${version} 已删除`
  })
}

onMounted(load)
</script>
<template>
  <div class="detail-pane">
    <p v-if="error" class="error">{{ error }}</p>
    <p v-if="notice" class="notice">{{ notice }}</p>
    <p v-if="loading" class="muted">加载中…</p>
    <template v-else-if="detail">
      <header>
        <h2>
          {{ detail.name }} <span class="fmt">{{ detail.format }}</span>
        </h2>
        <p class="muted">{{ detail.description }}</p>
      </header>
      <p class="meta">
        必含安全片段：
        <code v-for="f in detail.requiredFragments" :key="f">{{ f }}</code>
        <span v-if="!detail.requiredFragments.length" class="muted">无</span>
      </p>
      <section class="editor">
        <label for="prompt-editor">内容（保存会创建新草稿版本，已发布版本不可变）</label>
        <textarea
          id="prompt-editor"
          v-model="editorContent"
          rows="12"
          spellcheck="false"
          :disabled="busy"
        ></textarea>
        <div class="bar">
          <input v-model="changeNote" placeholder="变更说明（随草稿保存）" :disabled="busy" />
          <button class="primary" :disabled="busy || !editorContent.trim()" @click="saveDraft">
            存为草稿
          </button>
          <button :disabled="busy || detail.defaultContent == null" @click="resetDefault">
            恢复内置默认
          </button>
        </div>
      </section>
      <AdminPromptPreview
        :prompt-key="props.promptKey"
        :content="editorContent"
        :variables="detail.variables"
      />
      <section>
        <h3>版本历史（回滚 = 发布旧版本）</h3>
        <table>
          <thead>
            <tr>
              <th>版本</th>
              <th>状态</th>
              <th>说明</th>
              <th>创建</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="v in detail.versions" :key="v.id">
              <td>v{{ v.version }}</td>
              <td>
                <span class="badge" :class="v.status">{{ statusText[v.status] || v.status }}</span>
                <span v-if="v.id === detail.currentVersionId" class="muted">（当前）</span>
              </td>
              <td>{{ v.changeNote || '-' }}</td>
              <td class="muted">{{ v.createdBy }} · {{ v.createdAt?.slice(0, 16) }}</td>
              <td class="ops">
                <button :disabled="busy" @click="viewVersion(v.content)">查看</button>
                <button
                  v-if="v.status !== 'published'"
                  :disabled="busy"
                  @click="publish(v.id, v.version)"
                >
                  发布
                </button>
                <button
                  v-if="v.status === 'draft'"
                  class="danger"
                  :disabled="busy"
                  @click="removeDraft(v.id, v.version)"
                >
                  删除
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </section>
    </template>
  </div>
</template>
<style scoped>
.detail-pane {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}
h2 {
  margin: 0;
  font-size: var(--font-lg);
}
h3 {
  margin: 0 0 8px;
  font-size: var(--font-md);
}
.fmt {
  font-size: var(--font-sm);
  color: var(--info);
  background: var(--info-light);
  border-radius: var(--radius-pill);
  padding: 2px 8px;
  vertical-align: middle;
}
.muted {
  color: var(--text-secondary);
  font-weight: 400;
  font-size: var(--font-sm);
}
.meta {
  margin: 0;
  font-size: var(--font-sm);
}
.meta code {
  background: var(--surface-muted);
  border: 1px solid var(--border-dark);
  border-radius: var(--radius-xs);
  padding: 1px 6px;
  margin-right: 6px;
}
.editor label {
  display: block;
  font-size: var(--font-sm);
  color: var(--text-secondary);
  margin-bottom: 6px;
}
textarea {
  width: 100%;
  box-sizing: border-box;
  font-family: monospace;
  font-size: var(--font-sm);
  line-height: 1.6;
  border: 1px solid var(--border-dark);
  border-radius: var(--radius-sm);
  padding: 10px;
  resize: vertical;
}
.bar {
  display: flex;
  gap: 8px;
  margin-top: 8px;
  align-items: center;
}
.bar input {
  flex: 1;
  min-width: 180px;
  border: 1px solid var(--border-dark);
  border-radius: var(--radius-sm);
  padding: 7px 10px;
}
button {
  border: 1px solid var(--border-dark);
  background: var(--surface);
  border-radius: var(--radius-sm);
  padding: 7px 12px;
  cursor: pointer;
}
button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
button.primary {
  background: var(--primary);
  border-color: var(--primary);
  color: #fff;
}
button.danger {
  color: var(--danger);
  border-color: var(--danger-border);
}
table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--font-sm);
}
th,
td {
  text-align: left;
  padding: 8px 10px;
  border-bottom: 1px solid var(--border);
}
th {
  color: var(--text-secondary);
  font-weight: 500;
}
.badge {
  display: inline-block;
  padding: 2px 8px;
  border-radius: var(--radius-pill);
}
.badge.published {
  background: var(--success-light);
  color: var(--success);
}
.badge.draft {
  background: var(--warning-light);
  color: var(--warning);
}
.badge.archived {
  background: var(--surface-muted);
  color: var(--text-secondary);
}
.ops {
  white-space: nowrap;
}
.ops button {
  margin-right: 6px;
  padding: 4px 10px;
}
.error {
  color: var(--danger);
  margin: 0;
}
.notice {
  color: var(--success);
  margin: 0;
}
</style>
