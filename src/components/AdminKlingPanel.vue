<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import {
  fetchKlingStatus,
  queryKlingTask,
  submitKlingTask,
  type KlingStatus,
  type KlingTaskResult,
} from '../api/adminKling'

const EXAMPLE_PROMPT = '一只白色机械狐狸在雪山上奔跑，电影感光影'

interface ImageSlot {
  value: string
  type: string
  preview: string
}

interface HistoryEntry {
  taskId: string
  time: string
  summary: string
  status: string
  videoUrl: string
}

const HISTORY_KEY = 'kling-test-history'
const POLL_INTERVAL_MS = 5000

const status = ref<KlingStatus | null>(null)
const statusError = ref('')
const prompt = ref('')
const negativePrompt = ref('')
const duration = ref(5)
const mode = ref('pro')
const aspectRatio = ref('16:9')
const sound = ref('off')
const cfgScale = ref(0.5)
const elementIdsRaw = ref('')
const slots = reactive<ImageSlot[]>([
  { value: '', type: 'first_frame', preview: '' },
  { value: '', type: 'end_frame', preview: '' },
  { value: '', type: 'reference', preview: '' },
])
const videoUrl = ref('')
const videoReferType = ref('feature')
const videoKeepSound = ref('')
const fileInputs = ref<Array<HTMLInputElement | null>>([])
const busy = ref(false)
const formError = ref('')
const current = ref<{
  taskId: string
  status: string
  result: KlingTaskResult | null
  error: string
} | null>(null)
const history = ref<HistoryEntry[]>([])

let pollTimer: ReturnType<typeof setTimeout> | null = null

const ready = computed(() => !!status.value?.configured)
const filledImages = computed(() => slots.filter((s) => s.value.trim()))
const hasVideo = computed(() => !!videoUrl.value.trim())
const canSubmit = computed(
  () =>
    ready.value &&
    !busy.value &&
    (!!prompt.value.trim() || filledImages.value.length > 0 || hasVideo.value),
)

// 文档约束：使用参考视频时 sound 必须为 off
watch(hasVideo, (value) => {
  if (value) sound.value = 'off'
})

const loadStatus = async () => {
  statusError.value = ''
  try {
    status.value = await fetchKlingStatus()
  } catch (e) {
    statusError.value = e instanceof Error ? e.message : '状态加载失败'
  }
}

const loadHistory = () => {
  try {
    history.value = JSON.parse(localStorage.getItem(HISTORY_KEY) ?? '[]')
  } catch {
    history.value = []
  }
}
const saveHistory = () =>
  localStorage.setItem(HISTORY_KEY, JSON.stringify(history.value.slice(0, 20)))

const upsertHistory = (entry: HistoryEntry) => {
  const index = history.value.findIndex((item) => item.taskId === entry.taskId)
  if (index >= 0) history.value.splice(index, 1, entry)
  else history.value.unshift(entry)
  saveHistory()
}

onMounted(() => {
  void loadStatus()
  loadHistory()
})
onBeforeUnmount(() => {
  if (pollTimer) clearTimeout(pollTimer)
})

const triggerPick = (index: number) => fileInputs.value[index]?.click()

/** 本地图片转 Base64 data URI（Kling image_url 原生支持），不走服务端上传 */
const onFileChange = (index: number, event: Event) => {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  const reader = new FileReader()
  reader.onload = () => {
    slots[index].value = String(reader.result)
    slots[index].preview = String(reader.result)
  }
  reader.onerror = () => {
    formError.value = '图片读取失败'
  }
  reader.readAsDataURL(file)
}

const firstVideoUrl = (result: KlingTaskResult | null) =>
  result?.task_result?.videos?.[0]?.url ?? ''

const applyResult = (taskId: string, result: KlingTaskResult) => {
  const entry = history.value.find((item) => item.taskId === taskId)
  if (entry) {
    entry.status = result.task_status
    entry.videoUrl = firstVideoUrl(result) || entry.videoUrl
    saveHistory()
  }
}

const stopPoll = () => {
  if (pollTimer) clearTimeout(pollTimer)
  pollTimer = null
}

const poll = (taskId: string) => {
  stopPoll()
  const tick = async () => {
    try {
      const result = await queryKlingTask(taskId)
      if (current.value?.taskId === taskId) {
        current.value.status = result.task_status
        current.value.result = result
      }
      applyResult(taskId, result)
      if (result.task_status === 'submitted' || result.task_status === 'processing') {
        pollTimer = setTimeout(tick, POLL_INTERVAL_MS)
        return
      }
    } catch (e) {
      if (current.value?.taskId === taskId)
        current.value.error = e instanceof Error ? e.message : '查询失败'
    }
    pollTimer = null
  }
  pollTimer = setTimeout(tick, POLL_INTERVAL_MS)
}

const submit = async () => {
  if (!canSubmit.value) return
  busy.value = true
  formError.value = ''
  stopPoll()
  try {
    const created = await submitKlingTask({
      prompt: prompt.value,
      negativePrompt: negativePrompt.value,
      images: filledImages.value.map((s) => ({ imageUrl: s.value.trim(), type: s.type })),
      videos: hasVideo.value
        ? [
            {
              videoUrl: videoUrl.value.trim(),
              referType: videoReferType.value || undefined,
              keepOriginalSound: videoKeepSound.value || undefined,
            },
          ]
        : [],
      elementIds: elementIdsRaw.value
        .split(/[,，\s]+/)
        .map((item) => item.trim())
        .filter(Boolean),
      duration: duration.value,
      mode: mode.value,
      aspectRatio: aspectRatio.value,
      sound: sound.value,
      cfgScale: cfgScale.value,
    })
    current.value = {
      taskId: created.taskId,
      status: created.status || 'submitted',
      result: null,
      error: '',
    }
    upsertHistory({
      taskId: created.taskId,
      time: new Date().toLocaleString(),
      summary: `${duration.value}s · ${mode.value} · ${aspectRatio.value} · 声${sound.value}`,
      status: created.status || 'submitted',
      videoUrl: '',
    })
    poll(created.taskId)
  } catch (e) {
    formError.value = e instanceof Error ? e.message : '提交失败'
  } finally {
    busy.value = false
  }
}

const refreshEntry = async (entry: HistoryEntry) => {
  try {
    const result = await queryKlingTask(entry.taskId)
    entry.status = result.task_status
    entry.videoUrl = firstVideoUrl(result) || entry.videoUrl
    saveHistory()
  } catch (e) {
    entry.status = e instanceof Error ? e.message : '查询失败'
  }
}

const clearHistory = () => {
  history.value = []
  saveHistory()
}

const statusTone = (value: string) =>
  value === 'succeed' ? 'ok' : value === 'failed' || value.includes('失败') ? 'bad' : 'run'
</script>

<template>
  <div class="kling-panel">
    <div class="kling-head">
      <div>
        <h3>Kling V3 Omni 视频模型测试</h3>
        <p class="kling-sub">文生视频 / 首帧图生 / 首尾帧 / 多模态参考（图片 + 视频 + 主体）</p>
      </div>
      <div v-if="status" class="kling-meta">
        <span class="badge" :class="ready ? 'ok' : 'bad'">{{
          ready ? `Key 已配置 ${status.keyTail}` : 'Key 未配置'
        }}</span>
        <span class="wf">{{ status.model }} · {{ status.baseUrl }}</span>
      </div>
    </div>

    <p v-if="statusError" class="hint bad-text">{{ statusError }}</p>
    <p v-else-if="status && !ready" class="hint bad-text">
      Kling API Key 未配置：请设置 KLING_API_KEY（或复用 VIDEO_API_KEY/共享
      AIGC_TOKEN）并重启后端后刷新本页。
    </p>

    <div class="kling-form" :class="{ dim: !ready }">
      <div class="row prompt-row">
        <label class="form-label">提示词</label>
        <button type="button" class="ghost-btn" :disabled="!ready" @click="prompt = EXAMPLE_PROMPT">
          填入文生示例
        </button>
      </div>
      <textarea
        v-model="prompt"
        class="prompt-input"
        rows="4"
        :disabled="!ready"
        placeholder="文本提示词；引用主体用 <<>> 形式（与主体 ID 顺序对应）。提示词、图片、视频至少提供一项"
      ></textarea>
      <div class="row params">
        <label class="form-label">负向提示词</label>
        <input
          v-model="negativePrompt"
          class="text-input"
          :disabled="!ready"
          placeholder="可选，如：模糊, 变形"
        />
        <label class="form-label">主体 ID</label>
        <input
          v-model="elementIdsRaw"
          class="text-input"
          :disabled="!ready"
          placeholder="可选，多个用逗号分隔"
        />
      </div>

      <div class="row params">
        <label class="form-label">时长（秒）</label>
        <input
          v-model.number="duration"
          class="num-input"
          type="number"
          min="3"
          max="15"
          step="1"
          :disabled="!ready"
        />
        <label class="form-label">模式</label>
        <select v-model="mode" class="num-input" :disabled="!ready">
          <option v-for="item in status?.modes ?? ['std', 'pro', '4k']" :key="item" :value="item">
            {{ item }}{{ item === 'std' ? '（720P）' : item === 'pro' ? '（1080P）' : '（4K）' }}
          </option>
        </select>
        <label class="form-label">比例</label>
        <select v-model="aspectRatio" class="num-input" :disabled="!ready">
          <option
            v-for="item in status?.aspectRatios ?? ['16:9', '9:16', '1:1']"
            :key="item"
            :value="item"
          >
            {{ item }}
          </option>
        </select>
        <label class="form-label">声音</label>
        <select v-model="sound" class="num-input" :disabled="!ready || hasVideo">
          <option value="off">off</option>
          <option value="on">on</option>
        </select>
        <label class="form-label">相关性</label>
        <input
          v-model.number="cfgScale"
          class="num-input"
          type="number"
          min="0"
          max="1"
          step="0.1"
          :disabled="!ready"
        />
      </div>

      <div class="row slots">
        <div v-for="(slot, index) in slots" :key="index" class="slot">
          <div class="slot-head">
            <select v-model="slot.type" class="type-select" :disabled="!ready">
              <option value="first_frame">首帧</option>
              <option value="end_frame">尾帧</option>
              <option value="reference">参考图</option>
            </select>
            <button type="button" class="ghost-btn" :disabled="!ready" @click="triggerPick(index)">
              本地图片
            </button>
            <input
              :ref="(el) => (fileInputs[index] = el as HTMLInputElement | null)"
              type="file"
              accept="image/png,image/jpeg,image/webp"
              hidden
              @change="onFileChange(index, $event)"
            />
          </div>
          <input
            v-model="slot.value"
            class="slot-input"
            :disabled="!ready"
            placeholder="图片 URL，或点「本地图片」转 Base64"
          />
          <img
            v-if="slot.preview || slot.value.startsWith('http')"
            :src="slot.preview || slot.value"
            class="slot-thumb"
            alt="图片预览"
          />
        </div>
      </div>

      <div class="row params">
        <label class="form-label">参考视频</label>
        <input
          v-model="videoUrl"
          class="text-input wide"
          :disabled="!ready"
          placeholder="视频 URL（可选）"
        />
        <label class="form-label">参考类型</label>
        <input
          v-model="videoReferType"
          class="num-input"
          :disabled="!ready || !hasVideo"
          placeholder="feature"
        />
        <label class="form-label">保留原声</label>
        <select v-model="videoKeepSound" class="num-input" :disabled="!ready || !hasVideo">
          <option value="">默认</option>
          <option value="yes">yes</option>
          <option value="no">no</option>
        </select>
      </div>
      <p v-if="hasVideo" class="hint">使用参考视频时声音已强制为 off（接口约束）。</p>

      <div class="row submit-row">
        <button type="button" class="submit-btn" :disabled="!canSubmit" @click="submit">
          {{ busy ? '提交中…' : '提交生成' }}
        </button>
        <span v-if="formError" class="bad-text">{{ formError }}</span>
      </div>
    </div>

    <div v-if="current" class="kling-current">
      <div class="row">
        <span class="form-label">当前任务</span>
        <code>{{ current.taskId }}</code>
        <span class="badge" :class="statusTone(current.status)">{{ current.status }}</span>
      </div>
      <template v-if="current.status === 'succeed' && current.result">
        <video
          v-if="firstVideoUrl(current.result)"
          class="kling-video"
          :src="firstVideoUrl(current.result)"
          controls
          playsinline
        ></video>
        <p class="hint">生成成功，请尽快下载转存结果视频。</p>
      </template>
      <p v-else-if="current.status === 'failed'" class="bad-text">
        {{ current.result?.task_status_msg || '生成失败' }}
      </p>
      <p v-else class="hint">生成中，每 5 秒自动刷新…</p>
      <p v-if="current.error" class="bad-text">{{ current.error }}</p>
    </div>

    <div v-if="history.length" class="kling-history">
      <div class="row">
        <span class="form-label">历史记录</span>
        <button type="button" class="ghost-btn" @click="clearHistory">清空</button>
      </div>
      <table class="kling-table">
        <thead>
          <tr>
            <th>时间</th>
            <th>任务 ID</th>
            <th>参数</th>
            <th>状态</th>
            <th>结果</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="entry in history" :key="entry.taskId">
            <td>{{ entry.time }}</td>
            <td>
              <code>{{ entry.taskId.slice(-8) }}</code>
            </td>
            <td>{{ entry.summary }}</td>
            <td>
              <span class="badge" :class="statusTone(entry.status)">{{ entry.status }}</span>
            </td>
            <td>
              <a v-if="entry.videoUrl" :href="entry.videoUrl" target="_blank" rel="noopener"
                >查看视频</a
              >
              <span v-else>-</span>
            </td>
            <td>
              <button type="button" class="ghost-btn" @click="refreshEntry(entry)">刷新</button>
            </td>
          </tr>
        </tbody>
      </table>
      <p class="hint">历史仅保存在浏览器 localStorage（最多 20 条），换设备/清缓存后丢失。</p>
    </div>
  </div>
</template>

<style scoped>
.kling-panel {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 16px;
  box-shadow: var(--shadow-card);
}
.kling-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}
.kling-head h3 {
  margin: 0;
  font-size: var(--font-lg);
}
.kling-sub {
  margin: 4px 0 0;
  font-size: var(--font-sm);
  color: var(--text-secondary);
}
.kling-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  white-space: nowrap;
}
.wf {
  font-size: var(--font-sm);
  color: var(--text-secondary);
}
.dim {
  opacity: 0.55;
  pointer-events: none;
}
.row {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.prompt-row {
  justify-content: space-between;
}
.form-label {
  font-size: var(--font-md);
  color: var(--text);
  white-space: nowrap;
}
.prompt-input {
  width: 100%;
  box-sizing: border-box;
  border: 1px solid var(--border-dark);
  border-radius: var(--radius-sm);
  padding: 10px;
  font-size: var(--font-md);
  line-height: 1.5;
  resize: vertical;
}
.prompt-input:focus {
  outline: none;
  border-color: var(--primary);
}
.params {
  margin-top: 10px;
}
.text-input {
  border: 1px solid var(--border-dark);
  border-radius: var(--radius-sm);
  padding: 6px 10px;
  font-size: var(--font-md);
  flex: 1;
  min-width: 160px;
}
.num-input {
  border: 1px solid var(--border-dark);
  border-radius: var(--radius-sm);
  padding: 6px 10px;
  font-size: var(--font-md);
  width: 96px;
}
/* 下拉框按内容自适应宽度，避免「pro（1080P）」这类长选项被截断 */
select.num-input {
  width: auto;
  min-width: 148px;
}
.text-input:focus,
.num-input:focus {
  outline: none;
  border-color: var(--primary);
}
.slots {
  align-items: stretch;
  margin-top: 10px;
}
.slot {
  flex: 1;
  min-width: 200px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  border: 1px dashed var(--border);
  border-radius: var(--radius-sm);
  padding: 10px;
}
.slot-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.type-select {
  border: 1px solid var(--border-dark);
  border-radius: var(--radius-sm);
  padding: 5px 8px;
  font-size: var(--font-sm);
}
.slot-input {
  border: 1px solid var(--border-dark);
  border-radius: var(--radius-sm);
  padding: 6px 8px;
  font-size: var(--font-sm);
}
.type-select:focus,
.slot-input:focus {
  outline: none;
  border-color: var(--primary);
}
.slot-thumb {
  max-width: 100%;
  max-height: 90px;
  object-fit: contain;
  border-radius: var(--radius-sm);
  background: var(--surface-muted);
}
.submit-row {
  margin-top: 12px;
}
/* 与用户端主按钮一致的主操作按钮（渐变胶囊） */
.submit-btn {
  border: none;
  border-radius: var(--radius-pill);
  background: var(--primary-gradient);
  color: #fff;
  padding: 9px 20px;
  font-size: var(--font-md);
  font-weight: 600;
  cursor: pointer;
  box-shadow: 0 4px 12px rgba(255, 90, 44, 0.35);
  transition:
    filter 0.15s,
    transform 0.1s;
}
.submit-btn:hover:not(:disabled) {
  filter: brightness(1.05);
}
.submit-btn:active:not(:disabled) {
  transform: scale(0.98);
}
.submit-btn:disabled {
  opacity: 0.7;
  cursor: not-allowed;
}
.ghost-btn {
  border: 1px solid var(--border-dark);
  background: var(--surface);
  border-radius: var(--radius-sm);
  padding: 5px 12px;
  font-size: var(--font-sm);
  color: var(--primary);
  cursor: pointer;
  transition:
    border-color 0.15s,
    background 0.15s;
}
.ghost-btn:hover:not(:disabled) {
  border-color: var(--primary);
  background: var(--primary-light);
}
.ghost-btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}
.badge {
  border-radius: var(--radius-pill);
  padding: 3px 10px;
  font-size: var(--font-sm);
  border: 1px solid transparent;
  background: var(--surface-muted);
  color: var(--text-secondary);
}
.badge.ok {
  background: var(--success-light);
  color: var(--success);
}
.badge.bad {
  background: var(--danger-light);
  color: var(--danger);
}
.badge.run {
  background: var(--primary-light);
  color: var(--primary);
}
.hint {
  margin: 6px 0 0;
  font-size: var(--font-sm);
  color: var(--text-secondary);
}
.bad-text {
  font-size: var(--font-sm);
  color: var(--danger);
}
.kling-current,
.kling-history {
  border-top: 1px solid var(--border);
  padding-top: 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.kling-video {
  max-width: 560px;
  width: 100%;
  border-radius: var(--radius-sm);
  background: #000;
}
.kling-table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--font-sm);
}
.kling-table th,
.kling-table td {
  text-align: left;
  padding: 8px 10px;
  border-bottom: 1px solid var(--border);
}
.kling-table th {
  color: var(--text-secondary);
  font-weight: 600;
}
.kling-table tbody tr:hover {
  background: var(--surface-muted);
}
.text-input.wide {
  min-width: 280px;
}
</style>
