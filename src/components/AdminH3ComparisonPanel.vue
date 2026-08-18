<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import {
  fetchRunningHubComparisonSources,
  fetchRunningHubPresets,
  queryRunningHubTask,
  submitRunningHubComparison,
  type H3ComparisonSource,
  type H3TestMedia,
  type H3TestPreset,
} from '../api/adminRunningHub'

const POLL_INTERVAL_MS = 5000

const sources = ref<H3ComparisonSource[]>([])
const comparisons = ref<H3TestPreset[]>([])
const selectedUser = ref('')
const selectedTask = ref('')
const loading = ref(true)
const submittingLineId = ref('')
const refreshingTaskId = ref('')
const error = ref('')
const pollTimers = new Map<string, ReturnType<typeof setTimeout>>()

const isComparison = (preset: H3TestPreset) =>
  preset.inputMedia.some((media) => media.role === 'seedance_source')
const users = computed(() => [...new Set(sources.value.map((source) => source.username))])
const userSources = computed(() =>
  sources.value.filter((source) => source.username === selectedUser.value),
)
const tasks = computed(() => {
  const seen = new Set<string>()
  return userSources.value.filter((source) => {
    if (seen.has(source.taskId)) return false
    seen.add(source.taskId)
    return true
  })
})
const visibleSources = computed(() =>
  userSources.value.filter((source) => source.taskId === selectedTask.value),
)

watch(selectedUser, () => {
  selectedTask.value = tasks.value[0]?.taskId ?? ''
})

const sourceVideo = (preset: H3TestPreset) =>
  preset.inputMedia.find((media) => media.role === 'seedance_source')
const sourceCover = (preset: H3TestPreset) =>
  preset.inputMedia.find((media) => media.role === 'comparison_cover')
const h3Video = (preset: H3TestPreset) => preset.outputMedia.find((media) => media.type === 'video')
const sourceMeta = (preset: H3TestPreset): H3TestMedia | undefined => sourceVideo(preset)
const statusTone = (status: string) =>
  status === 'SUCCESS' ? 'ok' : status === 'FAILED' ? 'bad' : 'run'

const reloadComparisons = async () => {
  const loaded = await fetchRunningHubPresets()
  comparisons.value = loaded.items.filter(isComparison)
}

const load = async () => {
  loading.value = true
  error.value = ''
  try {
    const [loadedSources, loadedPresets] = await Promise.all([
      fetchRunningHubComparisonSources(),
      fetchRunningHubPresets(),
    ])
    sources.value = loadedSources.items
    comparisons.value = loadedPresets.items.filter(isComparison)
    selectedUser.value = users.value[0] ?? ''
    selectedTask.value = tasks.value[0]?.taskId ?? ''
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '对比数据加载失败'
  } finally {
    loading.value = false
  }
}

const stopPolling = (taskId: string) => {
  const timer = pollTimers.get(taskId)
  if (timer) clearTimeout(timer)
  pollTimers.delete(taskId)
}

const poll = (taskId: string) => {
  stopPolling(taskId)
  const tick = async () => {
    try {
      const result = await queryRunningHubTask(taskId)
      await reloadComparisons()
      if (result.status === 'RUNNING' || result.status === 'QUEUED') {
        pollTimers.set(taskId, setTimeout(tick, POLL_INTERVAL_MS))
        return
      }
    } catch (reason) {
      error.value = reason instanceof Error ? reason.message : '对比任务查询失败'
    }
    stopPolling(taskId)
  }
  pollTimers.set(taskId, setTimeout(tick, POLL_INTERVAL_MS))
}

const submitComparison = async (source: H3ComparisonSource) => {
  submittingLineId.value = source.lineId
  error.value = ''
  try {
    const created = await submitRunningHubComparison(source.lineId)
    comparisons.value.unshift(created)
    if (created.taskId) poll(created.taskId)
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : 'H3 对比任务提交失败'
  } finally {
    submittingLineId.value = ''
  }
}

const refreshComparison = async (preset: H3TestPreset) => {
  if (!preset.taskId) return
  refreshingTaskId.value = preset.taskId
  error.value = ''
  try {
    const result = await queryRunningHubTask(preset.taskId)
    await reloadComparisons()
    if (result.status === 'RUNNING' || result.status === 'QUEUED') poll(preset.taskId)
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '对比任务查询失败'
  } finally {
    refreshingTaskId.value = ''
  }
}

onMounted(load)
onBeforeUnmount(() => pollTimers.forEach((timer) => clearTimeout(timer)))
</script>

<template>
  <section class="comparison-panel">
    <div class="comparison-head">
      <div>
        <h4>H3 × Seedance 固定对比</h4>
        <p>选择用户已经生成的 Seedance 2.0 镜头，复用同一提示词和首帧生成 H3 视频。</p>
      </div>
      <button type="button" class="secondary-btn" :disabled="loading" @click="load">
        刷新数据
      </button>
    </div>

    <p v-if="error" class="error-text">{{ error }}</p>
    <p v-if="loading" class="empty-text">正在加载可对比镜头…</p>
    <template v-else>
      <div v-if="sources.length" class="comparison-filters">
        <label>
          用户
          <select v-model="selectedUser">
            <option v-for="username in users" :key="username" :value="username">
              {{ username }}
            </option>
          </select>
        </label>
        <label>
          已生成视频人物 / 分镜任务
          <select v-model="selectedTask">
            <option v-for="task in tasks" :key="task.taskId" :value="task.taskId">
              {{ task.projectName }} · {{ task.taskTitle }}
            </option>
          </select>
        </label>
      </div>
      <p v-else class="empty-text">暂无具备公网首帧和成片的 Seedance 2.0 通用分镜。</p>

      <div v-if="visibleSources.length" class="source-grid">
        <article v-for="source in visibleSources" :key="source.lineId" class="source-card">
          <img :src="source.coverUrl" :alt="`镜头 ${source.lineOrder + 1} 首帧`" />
          <div class="source-info">
            <div class="source-title">
              <strong>镜头 {{ source.lineOrder + 1 }}</strong>
              <span>{{ source.shotType === 'empty' ? '空镜' : '人物镜' }}</span>
              <span>{{ source.duration }} 秒</span>
            </div>
            <p>{{ source.prompt }}</p>
            <button
              type="button"
              class="primary-btn"
              :disabled="!!submittingLineId"
              @click="submitComparison(source)"
            >
              {{ submittingLineId === source.lineId ? '正在提交…' : '使用 H3 生成对比' }}
            </button>
          </div>
        </article>
      </div>
    </template>

    <div v-if="comparisons.length" class="reports">
      <h4>对比结果</h4>
      <article v-for="preset in comparisons" :key="preset.id" class="report-card">
        <div class="report-head">
          <div>
            <strong>{{ preset.name }}</strong>
            <p>
              {{ sourceMeta(preset)?.projectName }} · {{ sourceMeta(preset)?.taskTitle }} ·
              {{ sourceMeta(preset)?.shotType === 'empty' ? '空镜' : '人物镜' }}
            </p>
          </div>
          <span class="status" :class="statusTone(preset.taskStatus)">{{ preset.taskStatus }}</span>
        </div>
        <div class="video-compare">
          <figure>
            <figcaption>Seedance 2.0 原视频</figcaption>
            <video
              v-if="sourceVideo(preset)?.url"
              :src="sourceVideo(preset)?.url"
              controls
              playsinline
            />
          </figure>
          <figure>
            <figcaption>MiniMax H3 生成视频</figcaption>
            <video v-if="h3Video(preset)?.url" :src="h3Video(preset)?.url" controls playsinline />
            <div v-else class="video-pending">
              {{ preset.taskStatus === 'FAILED' ? '生成失败' : '生成中…' }}
            </div>
          </figure>
        </div>
        <details>
          <summary>查看提示词与共同参考首帧</summary>
          <div class="prompt-detail">
            <img
              v-if="sourceCover(preset)?.url"
              :src="sourceCover(preset)?.url"
              alt="共同参考首帧"
            />
            <pre>{{ preset.prompt }}</pre>
          </div>
        </details>
        <div class="report-foot">
          <span v-if="preset.usage?.consumeCoins">
            {{ preset.usage.consumeCoins }} RH 币 · {{ preset.usage.taskCostTime || '-' }} 秒
          </span>
          <code v-if="preset.taskId">{{ preset.taskId }}</code>
          <button
            v-if="preset.taskId && preset.taskStatus !== 'SUCCESS'"
            type="button"
            class="secondary-btn"
            :disabled="refreshingTaskId === preset.taskId"
            @click="refreshComparison(preset)"
          >
            {{ refreshingTaskId === preset.taskId ? '刷新中…' : '刷新状态' }}
          </button>
        </div>
      </article>
    </div>
  </section>
</template>

<style scoped>
.comparison-panel {
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 18px;
  border: 1px solid var(--primary-border);
  border-radius: var(--radius-md);
  background: var(--primary-light);
}
.comparison-head,
.report-head,
.report-foot,
.source-title {
  display: flex;
  align-items: center;
  gap: 10px;
}
.comparison-head,
.report-head {
  justify-content: space-between;
}
h4,
.comparison-head p,
.report-head p,
.source-info p,
figure {
  margin: 0;
}
.comparison-head p,
.report-head p,
.empty-text,
.report-foot {
  color: var(--text-secondary);
  font-size: var(--font-sm);
}
.comparison-filters {
  display: grid;
  grid-template-columns: minmax(160px, 0.5fr) minmax(260px, 1fr);
  gap: 12px;
}
.comparison-filters label {
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: var(--font-sm);
}
select {
  min-height: 38px;
  border: 1px solid var(--border-dark);
  border-radius: var(--radius-sm);
  background: var(--surface);
  padding: 6px 10px;
}
.source-grid,
.reports {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.source-card {
  display: grid;
  grid-template-columns: 200px minmax(0, 1fr);
  overflow: hidden;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--surface);
}
.source-card > img {
  width: 100%;
  height: 100%;
  min-height: 130px;
  object-fit: cover;
  background: var(--surface-dark);
}
.source-info {
  display: flex;
  min-width: 0;
  flex-direction: column;
  align-items: flex-start;
  gap: 9px;
  padding: 12px;
}
.source-title span,
.status {
  padding: 2px 8px;
  border-radius: var(--radius-pill);
  background: var(--surface-muted);
  color: var(--text-secondary);
  font-size: var(--font-sm);
}
.source-info p {
  display: -webkit-box;
  overflow: hidden;
  color: var(--text-secondary);
  font-size: var(--font-sm);
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 3;
}
.primary-btn,
.secondary-btn {
  border-radius: var(--radius-sm);
  padding: 7px 13px;
  cursor: pointer;
}
.primary-btn {
  margin-top: auto;
  border: 0;
  background: var(--primary-gradient);
  color: var(--surface);
}
.secondary-btn {
  border: 1px solid var(--border-dark);
  background: var(--surface);
  color: var(--primary);
}
button:disabled {
  cursor: not-allowed;
  opacity: 0.55;
}
.error-text {
  margin: 0;
  color: var(--danger);
  font-size: var(--font-sm);
}
.reports {
  padding-top: 4px;
}
.report-card {
  padding: 14px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--surface);
}
.status.ok {
  background: var(--success-light);
  color: var(--success);
}
.status.bad {
  background: var(--danger-light);
  color: var(--danger);
}
.status.run {
  background: var(--warning-light);
  color: var(--warning);
}
.video-compare {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  margin-top: 12px;
}
figcaption {
  margin-bottom: 6px;
  font-size: var(--font-sm);
  font-weight: 600;
}
video,
.video-pending {
  width: 100%;
  aspect-ratio: 16 / 9;
  border-radius: var(--radius-sm);
  background: var(--surface-dark);
}
.video-pending {
  display: grid;
  place-items: center;
  color: var(--text-secondary);
}
details {
  margin-top: 10px;
}
summary {
  color: var(--primary);
  cursor: pointer;
  font-size: var(--font-sm);
}
.prompt-detail {
  display: grid;
  grid-template-columns: 180px minmax(0, 1fr);
  gap: 10px;
  margin-top: 8px;
}
.prompt-detail img {
  width: 100%;
  border-radius: var(--radius-sm);
}
pre {
  max-height: 220px;
  margin: 0;
  overflow: auto;
  padding: 10px;
  border-radius: var(--radius-sm);
  background: var(--surface-muted);
  white-space: pre-wrap;
  font-size: var(--font-sm);
}
.report-foot {
  justify-content: flex-end;
  margin-top: 10px;
}
@media (max-width: 720px) {
  .comparison-filters,
  .video-compare,
  .prompt-detail,
  .source-card {
    grid-template-columns: 1fr;
  }
}
</style>
