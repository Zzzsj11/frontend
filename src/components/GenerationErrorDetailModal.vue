<script setup lang="ts">
import { computed, ref } from 'vue'
import type { ScriptLine } from '../types'
import { formatChinaDateTime } from '../utils/dateTime'
import AppIcon from './AppIcon.vue'
import BaseModal from './base/BaseModal.vue'

const props = defineProps<{
  open: boolean
  line: ScriptLine
  index: number
}>()
const emit = defineEmits<{ close: []; retry: [] }>()
const copied = ref<'job' | 'all' | ''>('')

const errorSummary = computed(
  () => props.line.generationErrorSummary || '提示词生成失败，请查看完整错误',
)
const fullError = computed(() => props.line.generationError || '服务端未记录具体错误信息')
const copyText = computed(() =>
  [
    `错误摘要：${errorSummary.value}`,
    `分镜序号：${props.index + 1}`,
    `分镜ID：${props.line.id}`,
    `工单ID：${props.line.generationJobId || '未记录'}`,
    `失败时间（东八区）：${props.line.generationFailedAt ? formatChinaDateTime(props.line.generationFailedAt) : '未记录'}`,
    '',
    '完整错误：',
    fullError.value,
  ].join('\n'),
)

const writeClipboard = async (value: string) => {
  if (navigator.clipboard?.writeText) return navigator.clipboard.writeText(value)
  const textarea = document.createElement('textarea')
  textarea.value = value
  textarea.style.position = 'fixed'
  textarea.style.opacity = '0'
  document.body.appendChild(textarea)
  textarea.select()
  document.execCommand('copy')
  textarea.remove()
}

const copy = async (kind: 'job' | 'all') => {
  const value = kind === 'job' ? props.line.generationJobId || '' : copyText.value
  if (!value) return
  await writeClipboard(value)
  copied.value = kind
  window.setTimeout(() => {
    if (copied.value === kind) copied.value = ''
  }, 1600)
}
</script>

<template>
  <BaseModal
    :open="open"
    title="生成失败详情"
    aria-label="生成失败详情"
    width="760px"
    max-height="86vh"
    @close="emit('close')"
  >
    <div class="error-detail-body">
      <div class="error-summary"><AppIcon name="alert" :size="16" />{{ errorSummary }}</div>
      <dl class="error-meta">
        <div>
          <dt>失败阶段</dt>
          <dd>逐镜提示词生成/落库</dd>
        </div>
        <div>
          <dt>分镜序号</dt>
          <dd>第 {{ index + 1 }} 条</dd>
        </div>
        <div>
          <dt>分镜 ID</dt>
          <dd class="mono">{{ line.id }}</dd>
        </div>
        <div>
          <dt>工单 ID</dt>
          <dd class="copy-row">
            <span class="mono">{{ line.generationJobId || '未记录' }}</span>
            <button v-if="line.generationJobId" type="button" @click="copy('job')">
              {{ copied === 'job' ? '已复制' : '复制' }}
            </button>
          </dd>
        </div>
        <div>
          <dt>失败时间</dt>
          <dd>
            {{
              line.generationFailedAt
                ? `${formatChinaDateTime(line.generationFailedAt)}（东八区）`
                : '未记录'
            }}
          </dd>
        </div>
        <div>
          <dt>是否可重试</dt>
          <dd>可以，重新生成不会删除其他已成功分镜</dd>
        </div>
      </dl>
      <section class="raw-error">
        <div class="raw-error-title">
          <strong>完整错误信息</strong>
          <button type="button" @click="copy('all')">
            {{ copied === 'all' ? '完整信息已复制' : '复制完整信息' }}
          </button>
        </div>
        <pre>{{ fullError }}</pre>
      </section>
    </div>
    <template #footer>
      <button type="button" class="secondary" @click="emit('close')">关闭</button>
      <button type="button" class="primary" @click="emit('retry')">重新生成</button>
    </template>
  </BaseModal>
</template>

<style scoped>
.error-detail-body {
  min-height: 0;
  overflow-y: auto;
  padding: 20px 22px;
}
.error-summary {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 14px;
  border: 1px solid color-mix(in srgb, var(--danger) 34%, transparent);
  border-radius: var(--radius-md);
  background: color-mix(in srgb, var(--danger) 7%, var(--surface));
  color: var(--danger);
  font-weight: 600;
}
.error-meta {
  display: grid;
  gap: 0;
  margin: 16px 0;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
}
.error-meta > div {
  display: grid;
  grid-template-columns: 120px minmax(0, 1fr);
  padding: 10px 12px;
  border-bottom: 1px solid var(--border);
}
.error-meta > div:last-child {
  border-bottom: 0;
}
dt {
  color: var(--text-secondary);
}
dd {
  min-width: 0;
  margin: 0;
  overflow-wrap: anywhere;
}
.mono,
pre {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}
.copy-row,
.raw-error-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
button {
  cursor: pointer;
}
.copy-row button,
.raw-error-title button {
  flex: 0 0 auto;
  border: 0;
  background: transparent;
  color: var(--primary);
}
.raw-error-title {
  margin-bottom: 8px;
}
pre {
  max-height: 280px;
  margin: 0;
  overflow: auto;
  padding: 14px;
  border-radius: var(--radius-md);
  background: var(--bg);
  color: var(--text);
  font-size: 12px;
  line-height: 1.6;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
.secondary,
.primary {
  min-width: 96px;
  padding: 9px 18px;
  border-radius: var(--radius-md);
}
.secondary {
  border: 1px solid var(--border);
  background: var(--surface);
  color: var(--text);
}
.primary {
  border: 1px solid var(--primary);
  background: var(--primary);
  color: white;
}
@media (max-width: 640px) {
  .error-meta > div {
    grid-template-columns: 1fr;
    gap: 4px;
  }
}
</style>
