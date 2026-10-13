<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useAuthStore } from '../stores/auth'
import AppIcon from './AppIcon.vue'
import { useProjectStore } from '../stores/project'
import type { MaterialExport } from '../types'

const store = useProjectStore()
const auth = useAuthStore()
const hidden = ref<Record<string, boolean>>({})
const deadlines = ref<Record<string, number>>({})
const now = ref(Date.now())
const noticeKey = (id: string) => `mv_export_notice_${auth.user?.id || 'guest'}_${id}`

const kinds = computed<Array<'video' | 'materials'>>(() =>
  store.activeStoryboardType === 'ass' && store.projectAudio
    ? ['video', 'materials']
    : ['materials'],
)
const missing = computed(
  () =>
    store.lines.filter((line) => {
      const asset =
        line.shot.assets.find((item) => item.id === line.shot.currentAssetId) || line.shot.assets[0]
      return !asset?.videoUrl
    }).length,
)
const latest = (kind: string) =>
  store.exportsByTaskId[store.activeTaskId || '']?.find(
    (item) => (item.kind || 'materials') === kind,
  )
const busy = (item?: MaterialExport) => !!item && ['queued', 'running'].includes(item.status)
const submitting = (kind: string) => store.exportSubmitting[`${store.activeTaskId}:${kind}`]
const label = (kind: string) => (kind === 'video' ? '合并并导出' : '导出素材')
const unavailable = (kind: string) =>
  kind === 'video' ? !store.lines.length || missing.value > 0 : !store.hasVideoAssets
const visible = (kind: string) => {
  const item = latest(kind)
  return Boolean(item && !hidden.value[item.id])
}
const hide = (item: MaterialExport) => {
  hidden.value[item.id] = true
  delete deadlines.value[item.id]
  sessionStorage.setItem(noticeKey(item.id), 'hidden')
}
const show = (item: MaterialExport) => {
  hidden.value[item.id] = false
  sessionStorage.removeItem(noticeKey(item.id))
  now.value = Date.now()
  if (item.status === 'ready') deadlines.value[item.id] = now.value + 5000
}
const countdown = (item: MaterialExport) =>
  Math.max(0, Math.ceil(((deadlines.value[item.id] || now.value) - now.value) / 1000))
watch(
  () => kinds.value.map((kind) => latest(kind)),
  (items) => {
    for (const item of items) {
      if (!item) continue
      if (!(item.id in hidden.value))
        hidden.value[item.id] = sessionStorage.getItem(noticeKey(item.id)) === 'hidden'
      if (item.status === 'ready' && !hidden.value[item.id] && !deadlines.value[item.id]) {
        now.value = Date.now()
        deadlines.value[item.id] = now.value + 5000
      }
      if (item.status !== 'ready') delete deadlines.value[item.id]
    }
  },
  { immediate: true, deep: true },
)
// 隐藏只收起提示卡，不取消后台导出；新工单仍会自动显示进度。
const timer = window.setInterval(() => {
  now.value = Date.now()
  for (const kind of kinds.value) {
    const item = latest(kind)
    if (
      item?.status === 'ready' &&
      deadlines.value[item.id] &&
      now.value >= deadlines.value[item.id]!
    )
      hide(item)
  }
}, 1000)
onBeforeUnmount(() => window.clearInterval(timer))
const stages = ['排队', '下载', '合成', '校验', '上传', '完成']
const stageIndex = (item: MaterialExport) =>
  item.status === 'ready'
    ? 5
    : item.progress >= 90
      ? 4
      : item.progress >= 85
        ? 3
        : item.progress >= 26
          ? 2
          : item.progress > 0
            ? 1
            : 0
</script>

<template>
  <div class="export-actions">
    <div v-for="kind in kinds" :key="kind" class="export-action">
      <div class="buttons">
        <button
          class="btn-outline"
          :disabled="submitting(kind) || busy(latest(kind)) || unavailable(kind)"
          @click="store.runExport(kind)"
        >
          {{
            submitting(kind)
              ? '正在提交…'
              : busy(latest(kind))
                ? `${label(kind)}中 ${latest(kind)!.progress}%`
                : latest(kind)?.status === 'failed'
                  ? `${label(kind)}重试`
                  : label(kind)
          }}
        </button>
        <a
          v-if="latest(kind)?.status === 'ready' && latest(kind)?.archiveUrl"
          class="btn-outline"
          :href="latest(kind)!.archiveUrl"
          download
          target="_blank"
          rel="noopener"
          >{{ kind === 'video' ? '下载成片' : '下载素材' }}</a
        >
        <button
          v-if="latest(kind) && !visible(kind)"
          class="btn-outline"
          @click="show(latest(kind)!)"
        >
          查看进度
        </button>
      </div>
      <small v-if="kind === 'video' && unavailable(kind)" class="hint">{{
        store.lines.length ? `还有 ${missing} 段视频未完成` : '暂无可合成分镜'
      }}</small>
      <div
        v-if="visible(kind)"
        class="export-progress"
        :class="{ failed: latest(kind)?.status === 'failed' }"
        :aria-label="`${label(kind)}进度`"
      >
        <div class="progress-heading">
          <small v-if="latest(kind)?.status === 'ready'" class="hint"
            >{{ countdown(latest(kind)!) }} 秒后自动隐藏</small
          >
          <span v-else>{{ label(kind) }}进度</span>
          <button
            class="hide-progress"
            :aria-label="`隐藏${label(kind)}进度`"
            title="隐藏进度，不取消任务"
            @click="hide(latest(kind)!)"
          >
            <AppIcon name="close" :size="12" />
          </button>
        </div>
        <div v-if="kind === 'video'" class="stages" aria-hidden="true">
          <span
            v-for="(stage, index) in stages"
            :key="stage"
            :class="{ reached: index <= stageIndex(latest(kind)!) }"
            >{{ stage }}</span
          >
        </div>
        <progress
          :value="latest(kind)!.progress"
          max="100"
          :aria-label="`${label(kind)}完成百分比`"
        />
        <p role="status">{{ latest(kind)!.stage }} · {{ latest(kind)!.progress }}%</p>
        <small v-if="store.exportConnectionIssues[latest(kind)!.id]" class="hint"
          >连接暂时中断，正在自动重连；后台任务继续执行</small
        >
        <small v-else-if="busy(latest(kind))" class="hint"
          >可离开或刷新页面，返回后继续查看进度</small
        >
        <p v-if="latest(kind)?.error" role="alert">{{ latest(kind)!.error }}</p>
      </div>
    </div>
  </div>
</template>

<style scoped>
.export-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin-left: auto;
  align-items: flex-start;
  max-width: 100%;
}
.export-action {
  min-width: 150px;
  max-width: 360px;
  flex: 1;
}
.buttons {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.buttons a {
  text-decoration: none;
}
.export-progress {
  margin-top: 8px;
  padding: 10px;
  background: var(--surface-muted);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  font-size: var(--font-sm);
}
.progress-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 6px;
}
.progress-heading .hint {
  margin: 0;
}
.hide-progress {
  display: grid;
  place-items: center;
  border: 0;
  padding: 4px;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
}
.hide-progress:hover {
  background: var(--border);
}
.export-progress p {
  margin: 6px 0;
  overflow-wrap: anywhere;
}
.export-progress progress {
  width: 100%;
  height: 8px;
  accent-color: var(--primary);
}
.stages {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  color: var(--text-secondary);
  margin-bottom: 6px;
}
.reached {
  color: var(--primary);
}
.hint {
  display: block;
  color: var(--text-secondary);
  margin-top: 6px;
}
.failed {
  border-color: var(--danger);
}
.failed [role='alert'] {
  color: var(--danger);
}
</style>
