<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import {
  createPromptOptimizerTask,
  fetchPromptOptimizerStatus,
  fetchPromptOptimizerTasks,
  queryPromptOptimizerTask,
  uploadPromptOptimizerMedia,
  type PromptOptimizerMedia,
  type PromptOptimizerMediaKind,
  type PromptOptimizerProvider,
  type PromptOptimizerStatus,
  type PromptOptimizerTask,
} from '../api/adminPromptOptimizer'

const status = ref<PromptOptimizerStatus | null>(null)
const provider = ref<PromptOptimizerProvider>('minimax')
const prompt = ref('')
const duration = ref(15)
const ratio = ref('16:9')
const media = ref<PromptOptimizerMedia[]>([])
const tasks = ref<PromptOptimizerTask[]>([])
const current = ref<PromptOptimizerTask | null>(null)
const loading = ref(false)
const uploading = ref(false)
const dragging = ref(false)
const error = ref('')
const copied = ref(false)
const fileInput = ref<HTMLInputElement | null>(null)
let pollTimer: ReturnType<typeof setTimeout> | null = null

const providerInfo = computed(() => status.value?.providers[provider.value])
const counts = computed(() => ({
  image: media.value.filter((item) => item.kind === 'image').length,
  video: media.value.filter((item) => item.kind === 'video').length,
  audio: media.value.filter((item) => item.kind === 'audio').length,
}))
const canSubmit = computed(
  () =>
    !!providerInfo.value?.configured &&
    !!prompt.value.trim() &&
    media.value.length > 0 &&
    !loading.value &&
    !uploading.value,
)

const limitFor = (kind: PromptOptimizerMediaKind) =>
  kind === 'image'
    ? status.value?.limits.images || 9
    : kind === 'video'
      ? status.value?.limits.videos || 3
      : status.value?.limits.audios || 3

const addFiles = async (files: File[]) => {
  if (!files.length) return
  error.value = ''
  uploading.value = true
  try {
    for (const file of files) {
      const kind = file.type.startsWith('image/')
        ? 'image'
        : file.type.startsWith('video/')
          ? 'video'
          : file.type.startsWith('audio/')
            ? 'audio'
            : null
      if (!kind) throw new Error(`${file.name} 不是支持的图片、视频或音频`)
      if (counts.value[kind] >= limitFor(kind)) throw new Error(`${kind} 素材已达到数量上限`)
      const uploaded = await uploadPromptOptimizerMedia(file)
      media.value.push({ ...uploaded, role: 'reference' })
    }
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '素材上传失败'
  } finally {
    uploading.value = false
  }
}

const onFileChange = async (event: Event) => {
  const input = event.target as HTMLInputElement
  const files = Array.from(input.files || [])
  input.value = ''
  await addFiles(files)
}

const onDrop = async (event: DragEvent) => {
  dragging.value = false
  await addFiles(Array.from(event.dataTransfer?.files || []))
}

const removeMedia = (index: number) => media.value.splice(index, 1)

const stopPoll = () => {
  if (pollTimer) clearTimeout(pollTimer)
  pollTimer = null
}

const updateTask = (task: PromptOptimizerTask) => {
  current.value = task
  const index = tasks.value.findIndex((item) => item.id === task.id)
  if (index >= 0) tasks.value[index] = task
  else tasks.value.unshift(task)
}

const poll = (id: string) => {
  stopPoll()
  const tick = async () => {
    try {
      const task = await queryPromptOptimizerTask(id)
      updateTask(task)
      if (task.status === 'queued' || task.status === 'running') {
        pollTimer = setTimeout(tick, 4000)
        return
      }
    } catch (reason) {
      error.value = reason instanceof Error ? reason.message : '查询优化任务失败'
    }
    pollTimer = null
  }
  pollTimer = setTimeout(tick, 1500)
}

const submit = async () => {
  if (!canSubmit.value) return
  loading.value = true
  error.value = ''
  copied.value = false
  stopPoll()
  try {
    const task = await createPromptOptimizerTask({
      provider: provider.value,
      prompt: prompt.value.trim(),
      duration: duration.value,
      ratio: ratio.value,
      media: media.value,
    })
    updateTask(task)
    if (task.status === 'queued' || task.status === 'running') poll(task.id)
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '提示词优化失败'
  } finally {
    loading.value = false
  }
}

const selectTask = (task: PromptOptimizerTask) => {
  current.value = task
  if (task.status === 'queued' || task.status === 'running') poll(task.id)
}

const copyOutput = async () => {
  if (!current.value?.outputPrompt) return
  await navigator.clipboard.writeText(current.value.outputPrompt)
  copied.value = true
  window.setTimeout(() => (copied.value = false), 1500)
}

onMounted(async () => {
  try {
    const [nextStatus, history] = await Promise.all([
      fetchPromptOptimizerStatus(),
      fetchPromptOptimizerTasks(),
    ])
    status.value = nextStatus
    tasks.value = history.items
    current.value = history.items[0] || null
    if (!nextStatus.providers.minimax.configured && nextStatus.providers.gemini.configured)
      provider.value = 'gemini'
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '提示词优化配置加载失败'
  }
})

onBeforeUnmount(stopPoll)
</script>

<template>
  <div class="optimizer-shell">
    <section class="control-panel">
      <header>
        <div>
          <h3>多参考提示词优化</h3>
          <p>混合上传图片、视频和音频，生成可直接用于 H3 Ref2VA 的结构化提示词。</p>
        </div>
      </header>

      <div class="provider-switch" role="group" aria-label="提示词优化模型">
        <button
          v-for="key in ['gemini', 'minimax'] as PromptOptimizerProvider[]"
          :key="key"
          type="button"
          :class="{ active: provider === key }"
          @click="provider = key"
        >
          <span>{{ key === 'gemini' ? 'Gemini' : 'MiniMax 官方' }}</span>
          <small>{{ status?.providers[key].model || '未配置' }}</small>
        </button>
      </div>

      <p v-if="providerInfo && !providerInfo.configured" class="config-warning">
        当前服务未配置后端密钥，请先设置对应的 PROMPT_OPTIMIZER_* 环境变量。
      </p>

      <label class="field-label" for="optimizer-prompt">目标描述</label>
      <div class="prompt-box">
        <textarea
          id="optimizer-prompt"
          v-model="prompt"
          maxlength="7000"
          placeholder="描述目标视频，并用图片1、视频1、音频1等自然语言说明各素材用途…"
        />
        <span>{{ prompt.length }}/7000</span>
      </div>

      <div class="media-title">
        <span class="field-label">参考素材</span>
        <div class="media-counts">
          <span>图片 {{ counts.image }}/{{ status?.limits.images || 9 }}</span>
          <span>视频 {{ counts.video }}/{{ status?.limits.videos || 3 }}</span>
          <span>音频 {{ counts.audio }}/{{ status?.limits.audios || 3 }}</span>
        </div>
      </div>

      <button
        type="button"
        class="drop-zone"
        :class="{ dragging }"
        :disabled="uploading"
        @click="fileInput?.click()"
        @dragenter.prevent="dragging = true"
        @dragover.prevent
        @dragleave.prevent="dragging = false"
        @drop.prevent="onDrop"
      >
        <b>＋</b>
        <span>{{ uploading ? '正在上传到 TOS…' : '点击或拖拽上传图片、视频或音频' }}</span>
      </button>
      <input
        ref="fileInput"
        class="file-input"
        type="file"
        multiple
        accept="image/*,video/mp4,video/quicktime,audio/wav,audio/mpeg"
        @change="onFileChange"
      />

      <div v-if="media.length" class="media-grid">
        <article v-for="(item, index) in media" :key="`${item.url}-${index}`" class="media-card">
          <img v-if="item.kind === 'image'" :src="item.thumbnailUrl || item.url" :alt="item.name" />
          <video v-else-if="item.kind === 'video'" :src="item.url" muted preload="metadata" />
          <div v-else class="audio-preview">♫</div>
          <div class="media-info">
            <b>{{ item.name }}</b>
            <small>{{ item.kind }}</small>
          </div>
          <button type="button" title="移除素材" aria-label="移除素材" @click="removeMedia(index)">
            ×
          </button>
        </article>
      </div>

      <div class="settings-row">
        <label>
          <span>时长</span>
          <input v-model.number="duration" type="range" min="4" max="15" step="1" />
          <b>{{ duration }} 秒</b>
        </label>
      </div>

      <div class="ratio-row" role="group" aria-label="画面比例">
        <span>画面比例</span>
        <button
          v-for="value in status?.ratios || ['adaptive', '16:9', '9:16']"
          :key="value"
          type="button"
          :class="{ active: ratio === value }"
          @click="ratio = value"
        >
          {{ value === 'adaptive' ? '自动' : value }}
        </button>
      </div>

      <p v-if="error" class="form-error">{{ error }}</p>
      <button class="optimize-button" type="button" :disabled="!canSubmit" @click="submit">
        {{
          loading
            ? '正在提交…'
            : provider === 'gemini'
              ? '使用 Gemini 优化提示词'
              : '使用 MiniMax 官方优化提示词'
        }}
      </button>
    </section>

    <section class="result-panel">
      <header class="result-head">
        <div>
          <h3>优化结果</h3>
          <p v-if="current">
            {{ current.model }} · {{ current.duration }} 秒 · {{ current.ratio }}
          </p>
          <p v-else>提交后将在这里显示六段结构化提示词。</p>
        </div>
        <button v-if="current?.outputPrompt" type="button" class="copy-button" @click="copyOutput">
          {{ copied ? '已复制' : '复制提示词' }}
        </button>
      </header>

      <div
        v-if="current?.status === 'queued' || current?.status === 'running'"
        class="result-state"
      >
        <span class="spinner" />
        <b>MiniMax 正在理解多参考素材</b>
        <small>任务 {{ current.providerTaskId || current.id }}</small>
      </div>
      <div v-else-if="current?.error" class="result-state error-state">
        <b>优化失败</b>
        <small>{{ current.error }}</small>
      </div>
      <textarea
        v-else-if="current?.outputPrompt"
        class="result-output"
        readonly
        :value="current.outputPrompt"
        aria-label="优化后的结构化提示词"
      />
      <div v-else class="empty-result">
        <span>H3</span>
        <p>上传参考素材并点击提示词优化</p>
      </div>

      <div v-if="tasks.length" class="history-strip">
        <button
          v-for="task in tasks.slice(0, 6)"
          :key="task.id"
          type="button"
          :class="{ active: current?.id === task.id }"
          @click="selectTask(task)"
        >
          <b>{{ task.provider === 'gemini' ? 'Gemini' : 'MiniMax' }}</b>
          <span>{{ task.status }}</span>
          <small>{{ task.duration }}s · {{ task.ratio }}</small>
        </button>
      </div>
    </section>
  </div>
</template>

<style scoped>
.optimizer-shell {
  display: grid;
  grid-template-columns: minmax(360px, 0.82fr) minmax(520px, 1.5fr);
  gap: 18px;
  min-height: calc(100vh - 110px);
}
.control-panel,
.result-panel {
  min-width: 0;
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  background: var(--surface);
  box-shadow: var(--shadow-sm);
}
.control-panel {
  padding: 22px;
  overflow-y: auto;
}
header h3,
.result-head h3 {
  margin: 0;
  color: var(--text);
  font-size: 18px;
}
header p,
.result-head p {
  margin: 6px 0 0;
  color: var(--text-muted);
  font-size: 12px;
  line-height: 1.6;
}
.provider-switch {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
  margin: 20px 0;
}
.provider-switch button {
  display: flex;
  flex-direction: column;
  gap: 3px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--surface-subtle);
  padding: 11px 14px;
  color: var(--text-muted);
  cursor: pointer;
}
.provider-switch button.active,
.ratio-row button.active {
  border-color: var(--primary);
  background: color-mix(in srgb, var(--primary) 13%, var(--surface));
  color: var(--primary);
  box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--primary) 35%, transparent);
}
.provider-switch span {
  font-weight: 700;
}
.provider-switch small {
  opacity: 0.75;
}
.config-warning,
.form-error {
  border-radius: var(--radius-xs);
  background: #fff4ed;
  padding: 9px 11px;
  color: #b42318;
  font-size: 12px;
}
.field-label {
  display: block;
  margin-bottom: 8px;
  color: var(--text);
  font-size: 13px;
  font-weight: 700;
}
.prompt-box {
  position: relative;
}
.prompt-box textarea {
  width: 100%;
  min-height: 150px;
  resize: vertical;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--surface-subtle);
  padding: 13px 14px 28px;
  color: var(--text);
  line-height: 1.6;
  box-sizing: border-box;
}
.prompt-box > span {
  position: absolute;
  right: 11px;
  bottom: 9px;
  color: var(--text-muted);
  font-size: 11px;
}
.media-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 20px;
}
.media-title .field-label {
  margin: 0;
}
.media-counts {
  display: flex;
  gap: 6px;
  color: var(--text-muted);
  font-size: 10px;
}
.media-counts span {
  border: 1px solid var(--border);
  border-radius: 99px;
  padding: 3px 7px;
}
.drop-zone {
  display: flex;
  width: 100%;
  min-height: 76px;
  align-items: center;
  justify-content: center;
  gap: 9px;
  border: 1px dashed var(--border-strong);
  border-radius: var(--radius-sm);
  background: var(--surface-subtle);
  color: var(--text-muted);
  cursor: pointer;
}
.drop-zone.dragging {
  border-color: var(--primary);
  background: color-mix(in srgb, var(--primary) 8%, var(--surface));
}
.drop-zone b {
  color: var(--primary);
  font-size: 24px;
}
.file-input {
  display: none;
}
.media-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
  margin-top: 10px;
}
.media-card {
  position: relative;
  display: grid;
  grid-template-columns: 54px minmax(0, 1fr) 24px;
  gap: 8px;
  align-items: center;
  border: 1px solid var(--border);
  border-radius: var(--radius-xs);
  padding: 6px;
  min-width: 0;
}
.media-card img,
.media-card video,
.audio-preview {
  width: 54px;
  height: 42px;
  border-radius: 6px;
  object-fit: cover;
  background: #101828;
}
.audio-preview {
  display: grid;
  place-items: center;
  color: #fff;
  font-size: 20px;
}
.media-info {
  display: flex;
  min-width: 0;
  flex-direction: column;
}
.media-info b {
  overflow: hidden;
  color: var(--text);
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.media-info small {
  color: var(--text-muted);
}
.media-card > button {
  border: 0;
  background: transparent;
  color: var(--text-muted);
  font-size: 20px;
  cursor: pointer;
}
.settings-row,
.ratio-row {
  margin-top: 14px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 10px 12px;
}
.settings-row label {
  display: grid;
  grid-template-columns: 42px 1fr 50px;
  gap: 10px;
  align-items: center;
  color: var(--text-muted);
  font-size: 12px;
}
.settings-row b {
  color: var(--primary);
}
.ratio-row {
  display: flex;
  gap: 5px;
  align-items: center;
  overflow-x: auto;
}
.ratio-row > span {
  margin-right: 4px;
  color: var(--text-muted);
  font-size: 12px;
  white-space: nowrap;
}
.ratio-row button {
  border: 1px solid transparent;
  border-radius: 7px;
  background: transparent;
  padding: 6px 9px;
  color: var(--text-muted);
  font-size: 11px;
  cursor: pointer;
  white-space: nowrap;
}
.optimize-button {
  width: 100%;
  margin-top: 14px;
  border: 0;
  border-radius: var(--radius-sm);
  background: var(--primary-gradient);
  padding: 12px;
  color: #fff;
  font-weight: 700;
  cursor: pointer;
}
.optimize-button:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.result-panel {
  display: flex;
  min-height: 660px;
  flex-direction: column;
  overflow: hidden;
}
.result-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  border-bottom: 1px solid var(--border);
  padding: 18px 20px;
}
.copy-button {
  border: 1px solid var(--border);
  border-radius: var(--radius-xs);
  background: var(--surface-subtle);
  padding: 7px 10px;
  color: var(--text);
  cursor: pointer;
}
.result-output {
  flex: 1;
  resize: none;
  border: 0;
  outline: 0;
  background: #101828;
  padding: 20px;
  color: #e4e7ec;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 12px;
  line-height: 1.7;
}
.empty-result,
.result-state {
  display: grid;
  flex: 1;
  place-content: center;
  justify-items: center;
  color: var(--text-muted);
  text-align: center;
}
.empty-result span {
  display: grid;
  width: 72px;
  height: 72px;
  place-items: center;
  border-radius: 22px;
  background: color-mix(in srgb, var(--primary) 12%, var(--surface));
  color: var(--primary);
  font-size: 24px;
  font-weight: 800;
}
.result-state small {
  margin-top: 8px;
}
.error-state {
  color: #b42318;
}
.spinner {
  width: 28px;
  height: 28px;
  margin-bottom: 14px;
  border: 3px solid var(--border);
  border-top-color: var(--primary);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}
.history-strip {
  display: grid;
  grid-template-columns: repeat(6, minmax(88px, 1fr));
  gap: 8px;
  border-top: 1px solid var(--border);
  padding: 12px;
  overflow-x: auto;
}
.history-strip button {
  display: flex;
  min-width: 90px;
  flex-direction: column;
  border: 1px solid var(--border);
  border-radius: var(--radius-xs);
  background: var(--surface-subtle);
  padding: 8px;
  color: var(--text-muted);
  text-align: left;
  cursor: pointer;
}
.history-strip button.active {
  border-color: var(--primary);
}
.history-strip b {
  color: var(--text);
  font-size: 11px;
}
.history-strip span,
.history-strip small {
  font-size: 10px;
}
@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
@media (max-width: 1100px) {
  .optimizer-shell {
    grid-template-columns: 1fr;
  }
  .result-panel {
    min-height: 600px;
  }
}
@media (max-width: 640px) {
  .control-panel {
    padding: 14px;
  }
  .media-grid {
    grid-template-columns: 1fr;
  }
}
</style>
