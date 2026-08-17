<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import {
  fetchRunningHubStatus,
  queryRunningHubTask,
  submitRunningHubTask,
  uploadRunningHubImage,
  type RunningHubStatus,
  type RunningHubTaskResult,
} from '../api/adminRunningHub'

/** 工作流默认示例：医生诊室三主体场景（来源：工作流 node 83 Text 默认值） */
const EXAMPLE_PROMPT = `subject_definitions:
<Subject 1> is the female doctor from <Picture 1>, with dark hair tied back in a neat bun, wearing a white doctor's coat over a green medical scrub top and a stethoscope around her neck.
<Subject 2> is the young male patient from <Picture 2>, with short black hair, wearing a solid blue t-shirt and black trousers.
<Subject 3> is the hospital outpatient consultation room from <Picture 3>, featuring a light-beige wall, a desk with a computer monitor, medical posters, a window with blinds, and chairs.

summary:
[reference generation] The target video establishes the consultation room in <Subject 3>. <Subject 1> reviews medical records while <Subject 2> watches nervously, leading into their initial dialogue exchange about his medical results.

retention_analysis:
<Subject 1> (appears in [Shot 1], [Shot 2]): fully_preserved - appearance, hair, doctor's coat, green scrub top, and stethoscope are retained from <Picture 1>.
<Subject 2> (appears in [Shot 1], [Shot 3]): fully_preserved - appearance, short black hair, blue t-shirt, and trousers are retained from <Picture 2>.
<Subject 3> (appears in [Shot 1], [Shot 2], [Shot 3]): fully_preserved - the consultation room layout, desk, window, and wall posters are retained from <Picture 3>.

detailed_description:
Live-action, realistic cinematic narrative style with natural daylight illumination inside a hospital room.
[Shot 1] A wide shot establishes <Subject 3>, the hospital consultation room. <Subject 1>, the female doctor with dark hair in a bun wearing a white coat and green scrub top, sits at the desk looking down and flipping through paper medical records on a clipboard. Across from her, <Subject 2>, the young male patient in a blue t-shirt, sits leaning forward, watching her face with an anxious and expectant expression. The camera holds a static shot for two seconds as paper rustles softly.
[Shot 2] At 00:04.000, the shot cuts to a medium close-up of <Subject 1> (S1), the female doctor. She slowly nods while skim-reading the pages. <Subject 1> (S1) speaks in a gentle, warm tone with a steady, reassuring pace: <d>[Chinese] 嗯，不错，所有指标都非常好，没什么问题。</d> She finishes the line with a mild nod.
[Shot 3] At 00:08.000, the shot cuts to a medium close-up of <Subject 2> (S2), the young male patient. He lifts his head slightly, his worried face instantly relaxing into a relieved smile. <Subject 2> (S2) says in an eager, lighthearted voice: <d>[Chinese] 是不是代表我彻底好了呀医生。</d> He rests his hands on his knees as the camera pushes in with small amplitude at slow speed toward his smiling face.

overall_soundscape:
The soft rustle of paper pages flipping, light keyboard clicks from the background desk, and quiet indoor room ambience.

non_diegetic_music:
N/A`

interface ImageSlot {
  value: string
  uploading: boolean
  preview: string
}

interface HistoryEntry {
  taskId: string
  time: string
  duration: number
  aspectRatio: string
  imageCount: number
  status: string
  videoUrl: string
}

const HISTORY_KEY = 'runninghub-test-history'
const POLL_INTERVAL_MS = 5000

const status = ref<RunningHubStatus | null>(null)
const statusError = ref('')
const prompt = ref('')
const duration = ref(8)
const aspectRatio = ref('16:9 (Widescreen)')
const seedRaw = ref('')
/** 一采（低清参考生成）/二采（放大精修）分辨率档位，工作流默认 0.4/0.9 MP */
const stage1Mp = ref(0.4)
const stage2Mp = ref(0.9)
const slots = reactive<ImageSlot[]>([
  { value: '', uploading: false, preview: '' },
  { value: '', uploading: false, preview: '' },
  { value: '', uploading: false, preview: '' },
])
const fileInputs = ref<Array<HTMLInputElement | null>>([])
const busy = ref(false)
const formError = ref('')
const current = ref<{
  taskId: string
  status: string
  result: RunningHubTaskResult | null
  error: string
} | null>(null)
const history = ref<HistoryEntry[]>([])

let pollTimer: ReturnType<typeof setTimeout> | null = null

const ready = computed(() => !!status.value?.configured)
const filledImages = computed(() => slots.map((s) => s.value.trim()).filter(Boolean))
const canSubmit = computed(
  () =>
    ready.value &&
    !busy.value &&
    !!prompt.value.trim() &&
    filledImages.value.length > 0 &&
    !slots.some((s) => s.uploading),
)

const loadStatus = async () => {
  statusError.value = ''
  try {
    status.value = await fetchRunningHubStatus()
    if (status.value.aspectRatios.length && !status.value.aspectRatios.includes(aspectRatio.value))
      aspectRatio.value = status.value.aspectRatios[0]
    const [defaultStage1, defaultStage2] = status.value.megapixelsDefault
    stage1Mp.value = defaultStage1
    stage2Mp.value = defaultStage2
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

const onFileChange = async (index: number, event: Event) => {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  const slot = slots[index]
  slot.uploading = true
  formError.value = ''
  try {
    const uploaded = await uploadRunningHubImage(file)
    slot.value = uploaded.fileName
    slot.preview = uploaded.downloadUrl
  } catch (e) {
    formError.value = e instanceof Error ? e.message : '上传失败'
  } finally {
    slot.uploading = false
  }
}

const fillTemplate = () => {
  prompt.value = EXAMPLE_PROMPT
}

const stopPoll = () => {
  if (pollTimer) clearTimeout(pollTimer)
  pollTimer = null
}

const firstVideoUrl = (result: RunningHubTaskResult | null) =>
  result?.results?.find((item) => item.outputType === 'mp4')?.url ?? result?.results?.[0]?.url ?? ''

const applyResult = (taskId: string, result: RunningHubTaskResult) => {
  const entry = history.value.find((item) => item.taskId === taskId)
  if (entry) {
    entry.status = result.status
    entry.videoUrl = firstVideoUrl(result) || entry.videoUrl
    saveHistory()
  }
}

const poll = (taskId: string) => {
  stopPoll()
  const tick = async () => {
    try {
      const result = await queryRunningHubTask(taskId)
      if (current.value?.taskId === taskId) {
        current.value.status = result.status
        current.value.result = result
      }
      applyResult(taskId, result)
      if (result.status === 'RUNNING' || result.status === 'QUEUED') {
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
    const seed = seedRaw.value.trim() === '' ? null : Number(seedRaw.value)
    const created = await submitRunningHubTask({
      prompt: prompt.value,
      duration: duration.value,
      aspectRatio: aspectRatio.value,
      images: filledImages.value,
      seed: seed !== null && Number.isFinite(seed) && seed >= 0 ? seed : null,
      stage1Megapixels: stage1Mp.value,
      stage2Megapixels: stage2Mp.value,
    })
    current.value = {
      taskId: created.taskId,
      status: created.status || 'QUEUED',
      result: null,
      error: '',
    }
    upsertHistory({
      taskId: created.taskId,
      time: new Date().toLocaleString(),
      duration: duration.value,
      aspectRatio: aspectRatio.value,
      imageCount: filledImages.value.length,
      status: created.status || 'QUEUED',
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
    const result = await queryRunningHubTask(entry.taskId)
    entry.status = result.status
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
  value === 'SUCCESS'
    ? 'ok'
    : value === 'FAILED' || value.startsWith('查询') || value.includes('失败')
      ? 'bad'
      : 'run'
</script>

<template>
  <div class="rh-panel">
    <div class="rh-head">
      <div>
        <h3>RunningHub 工作流测试</h3>
        <p class="rh-sub">MiniMax H3 多合一：多图参考生成（一采）→ 放大精修（二采）成片</p>
      </div>
      <div v-if="status" class="rh-meta">
        <span class="badge" :class="ready ? 'ok' : 'bad'">{{
          ready ? `Key 已配置 ${status.keyTail}` : 'Key 未配置'
        }}</span>
        <span class="wf">工作流 {{ status.workflowId }}</span>
      </div>
    </div>

    <p v-if="statusError" class="hint bad-text">{{ statusError }}</p>
    <p v-else-if="status && !ready" class="hint bad-text">
      RunningHub API Key 未配置：请在 backend/.env 写入 RUNNINGHUB_API_KEY
      并重启后端容器后刷新本页。
    </p>

    <div class="rh-form" :class="{ dim: !ready }">
      <div class="row prompt-row">
        <label class="form-label">提示词</label>
        <button type="button" class="ghost-btn" :disabled="!ready" @click="fillTemplate">
          填入示例模板
        </button>
      </div>
      <textarea
        v-model="prompt"
        class="prompt-input"
        rows="12"
        :disabled="!ready"
        placeholder="结构化模板：subject_definitions / summary / retention_analysis / detailed_description（[Shot N] 分镜 + <d>[Chinese] 台词）/ overall_soundscape"
      ></textarea>

      <div class="row params">
        <label class="form-label">时长（秒）</label>
        <input
          v-model.number="duration"
          class="num-input"
          type="number"
          min="4"
          max="15"
          step="1"
          :disabled="!ready"
        />
        <label class="form-label">宽高比</label>
        <select v-model="aspectRatio" class="num-input" :disabled="!ready">
          <option v-for="item in status?.aspectRatios ?? [aspectRatio]" :key="item" :value="item">
            {{ item }}
          </option>
        </select>
        <label class="form-label">种子</label>
        <input
          v-model="seedRaw"
          class="num-input"
          type="number"
          min="0"
          placeholder="随机"
          :disabled="!ready"
        />
      </div>

      <div class="row params">
        <label class="form-label">一采分辨率</label>
        <select v-model.number="stage1Mp" class="num-input wide" :disabled="!ready">
          <option
            v-for="preset in status?.megapixelsPresets ?? []"
            :key="preset.value"
            :value="preset.value"
          >
            {{ preset.value }} MP（16:9 约 {{ preset.size }}）
          </option>
        </select>
        <label class="form-label">二采分辨率</label>
        <select v-model.number="stage2Mp" class="num-input wide" :disabled="!ready">
          <option
            v-for="preset in status?.megapixelsPresets ?? []"
            :key="preset.value"
            :value="preset.value"
          >
            {{ preset.value }} MP（16:9 约 {{ preset.size }}）
          </option>
        </select>
      </div>
      <p class="hint">
        一采是低清参考生成（默认 0.4 MP），二采是放大精修出片（默认 0.9 MP）；尺寸标注按 16:9
        参考，其他比例由节点等比换算。
      </p>

      <div class="row slots">
        <div v-for="(slot, index) in slots" :key="index" class="slot">
          <div class="slot-head">
            <span class="form-label">参考图 {{ index + 1 }}</span>
            <button
              type="button"
              class="ghost-btn"
              :disabled="!ready || slot.uploading"
              @click="triggerPick(index)"
            >
              {{ slot.uploading ? '上传中…' : '本地上传' }}
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
            placeholder="上传后自动填入，或粘贴图片 URL"
          />
          <img
            v-if="slot.preview || slot.value.startsWith('http')"
            :src="slot.preview || slot.value"
            class="slot-thumb"
            alt="参考图预览"
          />
        </div>
      </div>
      <p class="hint">
        图位对应提示词中的 Picture 1/2/3；不足 3 张时后端自动用最后一张补齐槽位。上传文件 24
        小时内有效。
      </p>

      <div class="row submit-row">
        <button type="button" class="submit-btn" :disabled="!canSubmit" @click="submit">
          {{ busy ? '提交中…' : '提交生成（消耗 RH 币）' }}
        </button>
        <span v-if="formError" class="bad-text">{{ formError }}</span>
      </div>
    </div>

    <div v-if="current" class="rh-current">
      <div class="row">
        <span class="form-label">当前任务</span>
        <code>{{ current.taskId }}</code>
        <span class="badge" :class="statusTone(current.status)">{{ current.status }}</span>
      </div>
      <template v-if="current.status === 'SUCCESS' && current.result">
        <video
          v-if="firstVideoUrl(current.result)"
          class="rh-video"
          :src="firstVideoUrl(current.result)"
          controls
          playsinline
        ></video>
        <p v-if="current.result.usage" class="hint">
          消耗 {{ current.result.usage.consumeCoins ?? '-' }} RH 币 · 工作流耗时
          {{ current.result.usage.taskCostTime ?? '-' }} 秒 · 链接 24 小时内有效，请及时下载
        </p>
      </template>
      <p v-else-if="current.status === 'FAILED'" class="bad-text">
        {{ current.result?.errorMessage || '生成失败' }}
      </p>
      <p v-else class="hint">生成中，每 5 秒自动刷新（通常需 5~10 分钟）…</p>
      <p v-if="current.error" class="bad-text">{{ current.error }}</p>
    </div>

    <div v-if="history.length" class="rh-history">
      <div class="row">
        <span class="form-label">历史记录</span>
        <button type="button" class="ghost-btn" @click="clearHistory">清空</button>
      </div>
      <table class="rh-table">
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
            <td>
              {{ entry.duration }}s · {{ entry.aspectRatio.split(' ')[0] }} ·
              {{ entry.imageCount }} 图
            </td>
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
.rh-panel {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 16px;
  box-shadow: var(--shadow-card);
}
.rh-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}
.rh-head h3 {
  margin: 0;
  font-size: var(--font-lg);
}
.rh-sub {
  margin: 4px 0 0;
  font-size: var(--font-sm);
  color: var(--text-secondary);
}
.rh-meta {
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
  font-size: var(--font-sm);
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
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
.num-input {
  border: 1px solid var(--border-dark);
  border-radius: var(--radius-sm);
  padding: 6px 10px;
  font-size: var(--font-md);
  width: 110px;
}
/* 下拉框按内容自适应宽度，避免「16:9 (Wide)」这类长选项被截断 */
select.num-input {
  width: auto;
  min-width: 152px;
}
.num-input.wide {
  width: 240px;
}
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
}
.slot-input {
  border: 1px solid var(--border-dark);
  border-radius: var(--radius-sm);
  padding: 6px 8px;
  font-size: var(--font-sm);
}
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
.rh-current,
.rh-history {
  border-top: 1px solid var(--border);
  padding-top: 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.rh-video {
  max-width: 560px;
  width: 100%;
  border-radius: var(--radius-sm);
  background: #000;
}
.rh-table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--font-sm);
}
.rh-table th,
.rh-table td {
  text-align: left;
  padding: 8px 10px;
  border-bottom: 1px solid var(--border);
}
.rh-table th {
  color: var(--text-secondary);
  font-weight: 600;
}
.rh-table tbody tr:hover {
  background: var(--surface-muted);
}
</style>
