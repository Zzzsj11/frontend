<script setup lang="ts">
import { computed } from 'vue'
import { useProjectStore } from '../stores/project'
import type { MaterialExport } from '../types'

const store = useProjectStore()
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
      </div>
      <small v-if="kind === 'video' && unavailable(kind)" class="hint">{{
        store.lines.length ? `还有 ${missing} 段视频未完成` : '暂无可合成分镜'
      }}</small>
      <div
        v-if="latest(kind)"
        class="export-progress"
        :class="{ failed: latest(kind)?.status === 'failed' }"
        :aria-label="`${label(kind)}进度`"
      >
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
