<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { changeTaskVideoModel, type TaskVideoModelPlan } from '../api/domain'
import {
  loadGenerationModels,
  PROJECT_VIDEO_MODEL_IDS,
  VIDEO_MODEL_OPTIONS,
} from '../generationModels'
import { useProjectStore, DEFAULT_SHOT_OPTIONS } from '../stores/project'
import BaseModal from './base/BaseModal.vue'
import AppIcon from './AppIcon.vue'
import VideoModelSelect from './VideoModelSelect.vue'

const props = withDefaults(defineProps<{ disabled?: boolean }>(), { disabled: false })
const store = useProjectStore()
const open = ref(false)
const loading = ref(false)
const selected = ref('')
const plan = ref<TaskVideoModelPlan | null>(null)
const error = ref('')
const saved = ref('')
let requestVersion = 0
const visible = computed(
  () =>
    Boolean(store.activeTaskId) &&
    ['ass', 'general', 'general_random'].includes(store.activeStoryboardType || ''),
)
const current = computed(() => {
  const models = new Set(
    store.lines.map((line) => line.shotOptions?.videoModel || DEFAULT_SHOT_OPTIONS.videoModel),
  )
  return models.size > 1
    ? 'mixed'
    : [...models][0] ||
        String(store.activeStoryboardConfig.video_model || DEFAULT_SHOT_OPTIONS.videoModel)
})
const currentLabel = computed(() =>
  current.value === 'mixed'
    ? '混合'
    : VIDEO_MODEL_OPTIONS.find((m) => m.value === current.value)?.label || current.value,
)
const busyReason = computed(() =>
  store.batchShooting || store.lines.some((line) => line.shot.status === 'generating')
    ? '视频任务正在排队或生成，请完成后修改'
    : store.outlineLocked || store.lines.some((line) => line.generationStatus === 'running')
      ? '请等待大纲和分镜提示词生成完成'
      : !store.lines.length
        ? '请先生成分镜'
        : '',
)
const title = computed(() => busyReason.value || '统一修改当前子项目全部分镜的视频模型')
watch(
  () => store.activeTaskId,
  () => {
    ++requestVersion
    open.value = false
    loading.value = false
    store.taskVideoModelEditing = false
  },
)

async function preview() {
  const version = ++requestVersion
  plan.value = null
  error.value = ''
  if (!selected.value || !store.activeTaskId) return
  loading.value = true
  try {
    const result = await changeTaskVideoModel(store.activeTaskId, selected.value)
    if (version === requestVersion && open.value) plan.value = result
  } catch (e) {
    if (version === requestVersion)
      error.value = e instanceof Error ? e.message : '配置预览失败，请重试'
  } finally {
    if (version === requestVersion) loading.value = false
  }
}
function selectModel(value: string) {
  selected.value = value
  void preview()
}
async function show() {
  saved.value = ''
  loading.value = true
  error.value = ''
  open.value = true
  store.taskVideoModelEditing = true
  try {
    await loadGenerationModels(true, { required: true })
    selected.value =
      PROJECT_VIDEO_MODEL_IDS.has(current.value) &&
      VIDEO_MODEL_OPTIONS.some((m) => m.value === current.value)
        ? current.value
        : VIDEO_MODEL_OPTIONS.find((m) => PROJECT_VIDEO_MODEL_IDS.has(m.value))?.value || ''
    await preview()
  } catch (e) {
    error.value = e instanceof Error ? e.message : '模型目录加载失败'
    loading.value = false
  }
}
function close() {
  if (loading.value) return
  ++requestVersion
  open.value = false
  store.taskVideoModelEditing = false
}
async function save() {
  if (!plan.value || plan.value.blockers.length) return
  loading.value = true
  error.value = ''
  try {
    const result = await store.applyTaskVideoModel(plan.value)
    saved.value = `已将 ${result.count} 条分镜统一设置为 ${result.modelName}`
    open.value = false
    store.taskVideoModelEditing = false
  } catch (e) {
    plan.value = null
    error.value = e instanceof Error ? e.message : '保存失败，请重新预览'
  } finally {
    loading.value = false
  }
}
onMounted(() => {
  void loadGenerationModels()
})
onBeforeUnmount(() => {
  ++requestVersion
  store.taskVideoModelEditing = false
})
</script>

<template>
  <span v-if="visible" class="model-entry">
    <button
      class="btn-outline"
      :disabled="disabled || Boolean(busyReason)"
      :title="title"
      @click="show"
    >
      <AppIcon name="movie" :size="15" />视频模型：{{ currentLabel }} ▾
    </button>
    <span v-if="saved" class="saved" role="status">{{ saved }}</span>
  </span>
  <BaseModal
    :open="open"
    title="修改子项目视频模型"
    :loading="loading"
    width="620px"
    @close="close"
  >
    <div class="model-body">
      <p>
        当前模型：<strong>{{ currentLabel }}</strong> · 全部 {{ store.lines.length }} 条分镜
      </p>
      <VideoModelSelect
        :model-value="selected"
        label="目标视频模型"
        aria-label="目标视频模型"
        :disabled="loading"
        @update:model-value="selectModel"
      />
      <p class="hint">
        应用到当前子项目的全部分镜，包括单独修改过模型的镜头。已有视频继续保留；后续生成和重新生成使用新模型。
      </p>
      <p v-if="loading" role="status">正在检查并保存配置，请稍候…</p>
      <div v-if="plan?.adjustments.length" class="notice">
        <strong>以下参数将随模型调整</strong>
        <ul>
          <li v-for="(item, index) in plan.adjustments" :key="index">{{ item }}</li>
        </ul>
      </div>
      <div v-if="plan?.blockers.length" class="error" role="alert">
        <strong>请先处理以下镜头</strong>
        <ul>
          <li v-for="(item, index) in plan.blockers" :key="index">{{ item }}</li>
        </ul>
      </div>
      <p v-if="error" class="error" role="alert">{{ error }}</p>
      <button v-if="error" class="btn-outline" :disabled="loading" @click="preview">
        重新预览
      </button>
      <p v-if="plan && !plan.adjustments.length && !plan.blockers.length" class="hint">
        当前时长、清晰度和画幅均兼容，可直接应用。
      </p>
    </div>
    <template #footer>
      <button class="btn-outline" :disabled="loading" @click="close">取消</button>
      <button
        class="btn-primary"
        :disabled="loading || !plan || Boolean(plan.blockers.length)"
        @click="save"
      >
        {{ loading ? '处理中…' : '应用到全部分镜' }}
      </button>
    </template>
  </BaseModal>
</template>

<style scoped>
.model-entry {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}
.model-body {
  padding: 20px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 12px;
  color: var(--text);
}
.model-body p {
  margin: 0;
}
.hint {
  color: var(--text-secondary);
  font-size: var(--font-sm);
  line-height: 1.6;
}
.notice {
  padding: 12px;
  background: var(--warning-light);
  border-radius: var(--radius-sm);
}
.error {
  color: var(--danger);
}
.model-body ul {
  padding-left: 20px;
  margin: 8px 0 0;
  line-height: 1.7;
}
.saved {
  color: var(--success);
  font-size: var(--font-sm);
}
</style>
