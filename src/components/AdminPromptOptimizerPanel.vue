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
import {
  fetchRunningHubStatus,
  queryRunningHubTask,
  submitRunningHubTask,
  type RunningHubStatus,
  type RunningHubTaskResult,
} from '../api/adminRunningHub'

type GenerationMode = 'text' | 'first_frame' | 'first_last' | 'reference'

const status = ref<PromptOptimizerStatus | null>(null)
const provider = ref<PromptOptimizerProvider>('minimax')
const prompt = ref('')
const duration = ref(15)
const ratio = ref('16:9')
const media = ref<PromptOptimizerMedia[]>([])
const tasks = ref<PromptOptimizerTask[]>([])
const current = ref<PromptOptimizerTask | null>(null)
const generationMode = ref<GenerationMode>('reference')
const runningHubStatus = ref<RunningHubStatus | null>(null)
const generation = ref<RunningHubTaskResult | null>(null)
const generationLoading = ref(false)
const generationError = ref('')
const loading = ref(false)
const uploading = ref(false)
const dragging = ref(false)
const error = ref('')
const copied = ref(false)
const fileInput = ref<HTMLInputElement | null>(null)
const promptInput = ref<HTMLTextAreaElement | null>(null)
let pollTimer: ReturnType<typeof setTimeout> | null = null
let generationPollTimer: ReturnType<typeof setTimeout> | null = null

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
const generationImages = computed(() => media.value.filter((item) => item.kind === 'image'))
const generationVideos = computed(() => media.value.filter((item) => item.kind === 'video'))
const generationAudios = computed(() => media.value.filter((item) => item.kind === 'audio'))
const generationPrompt = computed(() => current.value?.outputPrompt?.trim() || prompt.value.trim())
const canGenerate = computed(() => {
  if (!runningHubStatus.value?.configured || generationLoading.value || !generationPrompt.value)
    return false
  if (media.value.some((item) => !item.runningHubFileName)) return false
  if (generationMode.value === 'text') return true
  if (generationMode.value === 'first_frame') return generationImages.value.length >= 1
  if (generationMode.value === 'first_last') return generationImages.value.length >= 2
  return (
    generationImages.value.length + generationVideos.value.length > 0 &&
    generationImages.value.length <= 6 &&
    generationVideos.value.length <= 1 &&
    generationAudios.value.length <= 3 &&
    media.value.length <= 10
  )
})
const generationHint = computed(() => {
  if (generationMode.value === 'text') return '无需参考素材，直接根据提示词生成。'
  if (generationMode.value === 'first_frame') return '使用第 1 张图片作为视频首帧。'
  if (generationMode.value === 'first_last') return '依次使用第 1、2 张图片作为首帧和尾帧。'
  return '最多使用 6 张图片、1 段视频和 3 段音频，合计不超过 10 个素材。'
})
const generationVideoUrl = computed(
  () =>
    generation.value?.results?.find((item) => item.outputType === 'mp4')?.url ||
    generation.value?.results?.[0]?.url ||
    '',
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

const referenceLabel = (item: PromptOptimizerMedia, index: number) => {
  const kindLabel = item.kind === 'image' ? '图片' : item.kind === 'video' ? '视频' : '音频'
  const kindIndex = media.value
    .slice(0, index + 1)
    .filter((entry) => entry.kind === item.kind).length
  return `${kindLabel}${kindIndex}`
}

const insertReference = async (item: PromptOptimizerMedia, index: number) => {
  const input = promptInput.value
  const token = `@${referenceLabel(item, index)}`
  if (!input) {
    prompt.value = `${prompt.value}${prompt.value ? ' ' : ''}${token} `
    return
  }
  const start = input.selectionStart
  const end = input.selectionEnd
  const prefix = prompt.value.slice(0, start)
  const suffix = prompt.value.slice(end)
  const leadingSpace = prefix && !prefix.endsWith(' ') ? ' ' : ''
  prompt.value = `${prefix}${leadingSpace}${token} ${suffix}`.slice(0, 7000)
  await Promise.resolve()
  const cursor = Math.min(prefix.length + leadingSpace.length + token.length + 1, 7000)
  input.focus()
  input.setSelectionRange(cursor, cursor)
}

const stopPoll = () => {
  if (pollTimer) clearTimeout(pollTimer)
  pollTimer = null
}

const stopGenerationPoll = () => {
  if (generationPollTimer) clearTimeout(generationPollTimer)
  generationPollTimer = null
}

const runningHubRatio = () => {
  const options =
    generationMode.value === 'text'
      ? runningHubStatus.value?.textAspectRatios
      : generationMode.value === 'first_frame' || generationMode.value === 'first_last'
        ? runningHubStatus.value?.firstFrameAspectRatios
        : runningHubStatus.value?.aspectRatios
  if (!options?.length) return '16:9 (Widescreen)'
  return options.find((value) => value.startsWith(ratio.value)) || options[0]
}

const pollGeneration = (taskId: string) => {
  stopGenerationPoll()
  const tick = async () => {
    try {
      const result = await queryRunningHubTask(taskId)
      generation.value = result
      if (result.status === 'RUNNING' || result.status === 'QUEUED') {
        generationPollTimer = setTimeout(tick, 4000)
        return
      }
      if (result.status !== 'SUCCESS')
        generationError.value = result.errorMessage || 'H3 视频生成失败'
    } catch (reason) {
      generationError.value = reason instanceof Error ? reason.message : '查询 H3 任务失败'
    }
    generationPollTimer = null
  }
  generationPollTimer = setTimeout(tick, 1500)
}

const generateVideo = async () => {
  if (!canGenerate.value || !runningHubStatus.value) return
  generationLoading.value = true
  generationError.value = ''
  generation.value = null
  stopGenerationPoll()
  try {
    const images = generationImages.value.map((item) => item.runningHubFileName!)
    const created = await submitRunningHubTask({
      mode: generationMode.value,
      prompt: generationPrompt.value,
      duration: duration.value,
      aspectRatio: runningHubRatio(),
      images:
        generationMode.value === 'text'
          ? []
          : images.slice(
              0,
              generationMode.value === 'first_last'
                ? 2
                : generationMode.value === 'first_frame'
                  ? 1
                  : 6,
            ),
      videos:
        generationMode.value === 'reference'
          ? generationVideos.value.slice(0, 1).map((item) => item.runningHubFileName!)
          : [],
      audios:
        generationMode.value === 'reference'
          ? generationAudios.value.slice(0, 3).map((item) => item.runningHubFileName!)
          : [],
      ...(generationMode.value === 'text'
        ? { textMegapixels: runningHubStatus.value.textMegapixelsDefault }
        : generationMode.value === 'first_frame' || generationMode.value === 'first_last'
          ? { firstFrameMegapixels: runningHubStatus.value.firstFrameMegapixelsDefault }
          : {
              stage1Megapixels: runningHubStatus.value.megapixelsDefault[0],
              stage2Megapixels: runningHubStatus.value.megapixelsDefault[1],
            }),
    })
    generation.value = { taskId: created.taskId, status: created.status }
    pollGeneration(created.taskId)
  } catch (reason) {
    generationError.value = reason instanceof Error ? reason.message : 'H3 视频任务提交失败'
  } finally {
    generationLoading.value = false
  }
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
    const [nextStatus, history, nextRunningHubStatus] = await Promise.all([
      fetchPromptOptimizerStatus(),
      fetchPromptOptimizerTasks(),
      fetchRunningHubStatus(),
    ])
    status.value = nextStatus
    tasks.value = history.items
    current.value = history.items[0] || null
    runningHubStatus.value = nextRunningHubStatus
    if (!nextStatus.providers.minimax.configured && nextStatus.providers.gemini.configured)
      provider.value = 'gemini'
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '提示词优化配置加载失败'
  }
})

onBeforeUnmount(() => {
  stopPoll()
  stopGenerationPoll()
})
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

      <div class="generation-mode" role="group" aria-label="H3 生成模式">
        <button
          v-for="item in [
            { value: 'text', label: '文生视频' },
            { value: 'first_frame', label: '首帧生成' },
            { value: 'first_last', label: '首尾帧生成' },
            { value: 'reference', label: '多参考生成' },
          ] as Array<{ value: GenerationMode; label: string }>"
          :key="item.value"
          type="button"
          :class="{ active: generationMode === item.value }"
          @click="generationMode = item.value"
        >
          {{ item.label }}
        </button>
      </div>
      <p class="generation-hint">{{ generationHint }}</p>

      <div class="prompt-title">
        <label class="field-label" for="optimizer-prompt">目标描述</label>
        <button v-if="prompt" type="button" @click="prompt = ''">一键清空</button>
      </div>
      <div class="prompt-box">
        <div v-if="media.length" class="prompt-references" aria-label="已上传素材引用">
          <button
            v-for="(item, index) in media"
            :key="`reference-${item.url}-${index}`"
            type="button"
            :class="`kind-${item.kind}`"
            :title="`插入 @${referenceLabel(item, index)}`"
            @click="insertReference(item, index)"
          >
            <img
              v-if="item.kind !== 'audio'"
              :src="item.thumbnailUrl || item.url"
              :alt="item.name"
            />
            <span v-else class="reference-audio-icon">♪</span>
            {{ referenceLabel(item, index) }}
          </button>
        </div>
        <textarea
          id="optimizer-prompt"
          ref="promptInput"
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

      <input
        ref="fileInput"
        class="file-input"
        type="file"
        multiple
        accept="image/*,video/mp4,video/quicktime,audio/wav,audio/mpeg"
        @change="onFileChange"
      />

      <div
        class="media-strip"
        :class="{ dragging }"
        @dragenter.prevent="dragging = true"
        @dragover.prevent
        @dragleave.prevent="dragging = false"
        @drop.prevent="onDrop"
      >
        <button
          type="button"
          class="add-media-card"
          :disabled="uploading"
          aria-label="上传参考素材"
          @click="fileInput?.click()"
        >
          <b>＋</b>
          <span>{{ uploading ? '上传中' : '添加素材' }}</span>
        </button>
        <article v-for="(item, index) in media" :key="`${item.url}-${index}`" class="media-card">
          <span class="media-order">{{ index + 1 }}</span>
          <img v-if="item.kind === 'image'" :src="item.thumbnailUrl || item.url" :alt="item.name" />
          <video v-else-if="item.kind === 'video'" :src="item.url" muted preload="metadata" />
          <div v-else class="audio-preview">♫</div>
          <div class="media-info">
            <b>{{ item.name }}</b>
            <small>{{ referenceLabel(item, index) }}</small>
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
      <button class="generate-button" type="button" :disabled="!canGenerate" @click="generateVideo">
        {{ generationLoading ? '正在提交 H3…' : '使用 H3 生成视频' }}
      </button>
      <p v-if="generationError" class="form-error">{{ generationError }}</p>
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

      <div v-if="generation" class="generation-result">
        <div>
          <b>H3 视频任务</b>
          <span>{{ generation.status }}</span>
          <small>{{ generation.taskId }}</small>
        </div>
        <video v-if="generationVideoUrl" :src="generationVideoUrl" controls playsinline />
        <div
          v-else-if="generation.status === 'RUNNING' || generation.status === 'QUEUED'"
          class="generation-progress"
        >
          <span class="spinner" />
          RunningHub 正在生成视频
        </div>
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
.generation-mode {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 6px;
  margin-bottom: 6px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--surface-subtle);
  padding: 5px;
}
.generation-hint {
  margin: 0 0 18px;
  color: var(--text-muted);
  font-size: var(--font-sm);
}
.generation-mode button {
  border: 1px solid transparent;
  border-radius: var(--radius-xs);
  background: transparent;
  padding: 8px 5px;
  color: var(--text-muted);
  font-size: var(--font-sm);
  cursor: pointer;
}
.generation-mode button.active {
  border-color: var(--primary-border);
  background: var(--primary-light);
  color: var(--primary);
  font-weight: 700;
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
.prompt-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.prompt-title button {
  border: 0;
  background: transparent;
  padding: 0 0 8px;
  color: var(--text-muted);
  cursor: pointer;
}
.prompt-title button:hover {
  color: var(--primary);
}
.prompt-box {
  position: relative;
  overflow: hidden;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--surface-subtle);
}
.prompt-box:focus-within {
  border-color: var(--primary);
  box-shadow: inset 0 0 0 1px var(--primary-border);
}
.prompt-references {
  display: flex;
  gap: 8px;
  padding: 12px 12px 0;
  overflow-x: auto;
}
.prompt-references button {
  display: inline-flex;
  flex: 0 0 auto;
  align-items: center;
  gap: 6px;
  border: 1px solid var(--primary-border);
  border-radius: var(--radius-pill);
  background: var(--primary-light);
  padding: 4px 9px 4px 5px;
  color: var(--primary);
  font-weight: 600;
  cursor: pointer;
}
.prompt-references button.kind-audio {
  border-color: var(--success);
  background: var(--success-light);
  color: var(--success);
}
.prompt-references img,
.reference-audio-icon {
  width: 24px;
  height: 24px;
  border-radius: var(--radius-xs);
  object-fit: cover;
}
.reference-audio-icon {
  display: grid;
  place-items: center;
  background: var(--success-light);
  font-size: var(--font-lg);
}
.prompt-box textarea {
  width: 100%;
  min-height: 150px;
  resize: vertical;
  border: 0;
  outline: 0;
  background: transparent;
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
  border-radius: var(--radius-pill);
  padding: 3px 7px;
}
.file-input {
  display: none;
}
.media-strip {
  display: flex;
  gap: 10px;
  min-height: 108px;
  margin-top: 10px;
  padding: 4px;
  overflow-x: auto;
  border-radius: var(--radius-sm);
}
.media-strip.dragging {
  background: var(--primary-light);
  box-shadow: inset 0 0 0 1px var(--primary-border);
}
.add-media-card {
  display: grid;
  min-width: 96px;
  min-height: 96px;
  flex: 0 0 96px;
  place-content: center;
  justify-items: center;
  gap: 5px;
  border: 1px dashed var(--border-strong);
  border-radius: var(--radius-sm);
  background: var(--surface-subtle);
  color: var(--text-muted);
  cursor: pointer;
}
.add-media-card b {
  color: var(--primary);
  font-size: 26px;
}
.add-media-card span {
  font-size: var(--font-sm);
}
.media-card {
  position: relative;
  display: flex;
  min-width: 112px;
  max-width: 112px;
  flex: 0 0 112px;
  flex-direction: column;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--surface-subtle);
  padding: 4px;
}
.media-card img,
.media-card video,
.audio-preview {
  width: 100%;
  height: 68px;
  border-radius: var(--radius-xs);
  object-fit: cover;
  background: var(--surface-dark);
}
.audio-preview {
  display: grid;
  place-items: center;
  color: var(--surface);
  font-size: 20px;
}
.media-order {
  position: absolute;
  top: 8px;
  left: 8px;
  display: grid;
  width: 24px;
  height: 24px;
  place-items: center;
  border-radius: var(--radius-pill);
  background: var(--primary);
  color: var(--surface);
  font-size: var(--font-sm);
  font-weight: 700;
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
  position: absolute;
  top: 7px;
  right: 7px;
  display: grid;
  width: 24px;
  height: 24px;
  place-items: center;
  border-radius: var(--radius-pill);
  border: 0;
  background: var(--surface-dark);
  color: var(--surface);
  font-size: var(--font-lg);
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
.generate-button {
  width: 100%;
  margin-top: 8px;
  border: 1px solid var(--primary);
  border-radius: var(--radius-sm);
  background: var(--surface);
  padding: 12px;
  color: var(--primary);
  font-weight: 700;
  cursor: pointer;
}
.generate-button:hover:not(:disabled) {
  background: var(--primary-light);
}
.generate-button:disabled {
  opacity: 0.4;
  cursor: not-allowed;
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
.generation-result {
  border-top: 1px solid var(--border);
  padding: 14px;
}
.generation-result > div:first-child {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
  color: var(--text-muted);
}
.generation-result > div:first-child b {
  color: var(--text);
}
.generation-result > div:first-child small {
  margin-left: auto;
}
.generation-result video {
  display: block;
  width: 100%;
  max-height: 440px;
  border-radius: var(--radius-sm);
  background: var(--surface-dark);
}
.generation-progress {
  display: flex;
  min-height: 180px;
  align-items: center;
  justify-content: center;
  gap: 12px;
  border-radius: var(--radius-sm);
  background: var(--surface-subtle);
  color: var(--text-muted);
}
.generation-progress .spinner {
  margin: 0;
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
  .generation-mode {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
