<script setup lang="ts">
import ImageZoom from './ImageZoom.vue'
import BaseSelect from './base/BaseSelect.vue'
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import {
  fetchCreativeStatus,
  optimizeCreativePrompt,
  queryCreativeOptimization,
  uploadCreativeMedia,
  type CreativeOptimization,
  type CreativeProvider,
  type CreativeStatus,
} from '../api/creative'
import type { CreativeReferenceMedia, ShotGenOptions } from '../types'
import { DEFAULT_SHOT_OPTIONS, useProjectStore } from '../stores/project'
import {
  VIDEO_MODEL_OPTIONS,
  videoModelCapabilities,
  videoDurationChoices,
  videoRatioChoices,
  videoResolutionChoices,
  loadGenerationModels,
} from '../generationModels'
import BaseModal from './base/BaseModal.vue'
import VideoModelSelect from './VideoModelSelect.vue'
import AppIcon from './AppIcon.vue'
import {
  creativeModeReady,
  creativeReferences,
  type CreativeGenerationMode,
} from '../utils/creativeVideo'

type GenerationMode = CreativeGenerationMode
const store = useProjectStore()
const status = ref<CreativeStatus | null>(null)
const provider = ref<CreativeProvider>('gemini')
const mode = ref<GenerationMode>('reference')
const originalPrompt = ref('')
const optimizedPrompt = ref('')
const media = ref<CreativeReferenceMedia[]>([])
const duration = ref(15)
const ratio = ref<ShotGenOptions['ratio']>('16:9')
const videoModel = ref('minimax-h3-all-in-one')
const task = ref<CreativeOptimization | null>(null)
const loading = ref(false)
const uploading = ref(false)
const error = ref('')
const fileInput = ref<HTMLInputElement | null>(null)
let pollTimer: ReturnType<typeof setTimeout> | undefined

const counts = computed(() => ({
  image: media.value.filter((item) => item.kind === 'image').length,
  video: media.value.filter((item) => item.kind === 'video').length,
  audio: media.value.filter((item) => item.kind === 'audio').length,
}))
const canOptimize = computed(() => {
  if (!originalPrompt.value.trim() || loading.value || uploading.value) return false
  if (provider.value === 'minimax' && !media.value.length) return false
  return Boolean(status.value?.providers[provider.value].configured)
})
const canCreate = computed(() => Boolean(optimizedPrompt.value.trim()) && !loading.value)
const videoCaps = computed(() => videoModelCapabilities(videoModel.value))
const durationChoices = computed(() => videoDurationChoices(videoModel.value))
const ratios = computed(() => videoRatioChoices(videoModel.value))
watch(videoModel, () => {
  if (!durationChoices.value.includes(duration.value))
    duration.value = durationChoices.value[0] ?? 5
  if (!ratios.value.includes(ratio.value)) ratio.value = ratios.value[0] ?? '16:9'
  if (!(videoCaps.value.referenceModes as string[] | undefined)?.includes(mode.value))
    mode.value = 'text'
})
const referenceLimits = computed(() => ({
  image: Number(videoCaps.value.referenceImage?.max ?? 6),
  video: Number((videoCaps.value.referenceVideo as { max?: number } | undefined)?.max ?? 1),
  audio: Number((videoCaps.value.referenceAudio as { max?: number } | undefined)?.max ?? 3),
  total: Number(videoCaps.value.referenceTotalMax ?? 50),
  audioRequiresVisual: Boolean(videoCaps.value.referenceAudioRequiresVisual),
}))
const modeReady = computed(
  () =>
    creativeModeReady(mode.value, media.value, referenceLimits.value) &&
    counts.value.image <= Number(videoCaps.value.referenceImage?.max ?? 6) &&
    counts.value.video <=
      Number((videoCaps.value.referenceVideo as { max?: number } | undefined)?.max ?? 1) &&
    counts.value.audio <=
      Number((videoCaps.value.referenceAudio as { max?: number } | undefined)?.max ?? 3) &&
    (videoCaps.value.referenceModes as string[] | undefined)?.includes(mode.value),
)
const labelOf = (item: CreativeReferenceMedia, index: number) => {
  const label = item.kind === 'image' ? '图片' : item.kind === 'video' ? '视频' : '音频'
  return `${label}${media.value.slice(0, index + 1).filter((entry) => entry.kind === item.kind).length}`
}
const addFiles = async (files: File[]) => {
  uploading.value = true
  error.value = ''
  try {
    for (const file of files) {
      const kind = file.type.startsWith('image/')
        ? 'image'
        : file.type.startsWith('video/')
          ? 'video'
          : file.type.startsWith('audio/')
            ? 'audio'
            : null
      if (!kind) throw new Error(`${file.name} 不是支持的媒体格式`)
      const limit = referenceLimits.value[kind]
      if (counts.value[kind] >= limit) throw new Error(`${kind} 素材已达到数量上限`)
      media.value.push(await uploadCreativeMedia(file))
    }
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '素材上传失败'
  } finally {
    uploading.value = false
  }
}
const onFiles = async (event: Event) => {
  const input = event.target as HTMLInputElement
  await addFiles(Array.from(input.files || []))
  input.value = ''
}
const poll = (id: string) => {
  const tick = async () => {
    try {
      task.value = await queryCreativeOptimization(id)
      if (task.value.status === 'queued' || task.value.status === 'running') {
        pollTimer = setTimeout(tick, 3500)
      } else if (task.value.status === 'succeeded') optimizedPrompt.value = task.value.outputPrompt
      else error.value = task.value.error || '提示词优化失败'
    } catch (reason) {
      error.value = reason instanceof Error ? reason.message : '查询优化任务失败'
    }
  }
  pollTimer = setTimeout(tick, 1200)
}
const optimize = async () => {
  if (!canOptimize.value) return
  loading.value = true
  error.value = ''
  try {
    task.value = await optimizeCreativePrompt({
      provider: provider.value,
      prompt: originalPrompt.value.trim(),
      duration: duration.value,
      ratio: ratio.value,
      media: media.value,
    })
    if (task.value.status === 'succeeded') optimizedPrompt.value = task.value.outputPrompt
    else if (task.value.status === 'queued' || task.value.status === 'running') poll(task.value.id)
    else error.value = task.value.error || '提示词优化失败'
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '提示词优化失败'
  } finally {
    loading.value = false
  }
}
const create = async () => {
  if (!canCreate.value || !modeReady.value) return
  loading.value = true
  error.value = ''
  try {
    const references = creativeReferences(mode.value, media.value)
    const options: ShotGenOptions = {
      ...DEFAULT_SHOT_OPTIONS,
      duration: duration.value,
      ratio: ratio.value,
      videoModel: videoModel.value,
      resolution: (videoResolutionChoices(videoModel.value)[0] ??
        '720p') as ShotGenOptions['resolution'],
      h3Mode: mode.value,
      h3FirstFrameUrl: references.firstFrameUrl,
      h3LastFrameUrl: references.lastFrameUrl,
      referenceImageUrls: references.imageUrls,
      referenceVideoUrls: references.videoUrls,
      referenceAudioUrls: references.audioUrls,
    }
    const line = await store.addCreativeLine({
      originalPrompt: originalPrompt.value.trim(),
      optimizedPrompt: optimizedPrompt.value.trim(),
      referenceMedia: media.value,
      optimizerProvider: provider.value,
      optimizationTaskId: task.value?.id,
      options,
    })
    void store.generateShotFor(line.id, line.optimizedPrompt, options)
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '创建创意分镜失败'
  } finally {
    loading.value = false
  }
}
onMounted(async () => {
  try {
    await loadGenerationModels()
    if (!VIDEO_MODEL_OPTIONS.some((item) => item.value === videoModel.value))
      videoModel.value = VIDEO_MODEL_OPTIONS[0]?.value || 'minimax-h3-all-in-one'
    status.value = await fetchCreativeStatus()
    if (!status.value.providers.minimax.configured && status.value.providers.gemini.configured)
      provider.value = 'gemini'
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '加载优化服务失败'
  }
})
onBeforeUnmount(() => pollTimer && clearTimeout(pollTimer))
</script>

<template>
  <BaseModal
    :open="store.creativeOpen"
    title="创意视频"
    width="920px"
    :loading="loading"
    @close="store.closeCreative()"
  >
    <div class="creative-body">
      <p class="intro">混合图片、视频和音频，优化为 H3 可直接使用的结构化提示词并加入当前项目。</p>
      <div class="switch two" role="group" aria-label="提示词优化模型">
        <button
          v-for="key in [
            'gemini',
            ...(status?.providers.minimax.configured ? ['minimax'] : []),
          ] as CreativeProvider[]"
          :key="key"
          :class="{ active: provider === key }"
          @click="provider = key"
        >
          {{ key === 'gemini' ? 'Gemini' : 'MiniMax 官方'
          }}<small>{{ status?.providers[key].model || '未配置' }}</small>
        </button>
      </div>
      <p class="hint">视频参考按首、中、尾画面及音轨分析，视频和音频参考最长 15 秒。</p>
      <div class="switch modes" role="group" aria-label="视频生成模式">
        <button
          v-for="item in [
            { key: 'text', label: '文生视频' },
            { key: 'first_frame', label: '首帧生成' },
            { key: 'first_last', label: '首尾帧生成' },
            { key: 'reference', label: '多参考生成' },
          ] as Array<{ key: GenerationMode; label: string }>"
          :key="item.key"
          :class="{ active: mode === item.key }"
          :disabled="!(videoCaps.referenceModes as string[] | undefined)?.includes(item.key)"
          @click="mode = item.key"
        >
          {{ item.label }}
        </button>
      </div>
      <VideoModelSelect v-model="videoModel" label="视频模型" />
      <label
        >目标描述<textarea
          v-model="originalPrompt"
          maxlength="7000"
          placeholder="描述目标视频，并说明图片1、视频1、音频1等素材用途…"
        />
      </label>
      <div v-if="media.length" class="reference-tags">
        <span v-for="(item, index) in media" :key="item.url">{{ labelOf(item, index) }}</span>
      </div>
      <div class="media-head">
        <b>参考素材</b
        ><span
          >图片 {{ counts.image }}/{{ referenceLimits.image }} · 视频 {{ counts.video }}/{{
            referenceLimits.video
          }}
          · 音频 {{ counts.audio }}/{{ referenceLimits.audio }}</span
        >
      </div>
      <input
        ref="fileInput"
        hidden
        type="file"
        multiple
        accept="image/*,video/*,audio/*"
        @change="onFiles"
      />
      <div class="media-strip">
        <button class="add" :disabled="uploading" @click="fileInput?.click()">
          <AppIcon name="plus" :size="18" />{{ uploading ? '上传中' : '添加素材' }}
        </button>
        <article v-for="(item, index) in media" :key="item.url">
          <img v-if="item.kind === 'image'" :src="item.thumbnailUrl || item.url" alt="" /><ImageZoom
            v-if="item.kind === 'image'"
            :src="item.url"
            :alt="`参考图片 ${index + 1}`"
          /><span v-if="item.kind !== 'image'">{{ item.kind === 'video' ? '视频' : '音频' }}</span
          ><button title="移除素材" @click="media.splice(index, 1)">×</button>
        </article>
      </div>
      <div class="settings">
        <label
          >时长
          <BaseSelect v-model.number="duration">
            <option v-for="value in durationChoices" :key="value" :value="value">
              {{ value }} 秒
            </option>
          </BaseSelect></label
        >
        <div>
          <span>画面比例</span
          ><button
            v-for="value in ratios"
            :key="value"
            :class="{ active: ratio === value }"
            @click="ratio = value"
          >
            {{ value }}
          </button>
        </div>
      </div>
      <button class="primary" :disabled="!canOptimize" @click="optimize">
        {{
          loading
            ? '处理中…'
            : `使用 ${provider === 'gemini' ? 'Gemini' : 'MiniMax 官方'} 优化提示词`
        }}
      </button>
      <label
        >优化后的提示词<textarea
          v-model="optimizedPrompt"
          class="optimized"
          placeholder="优化结果会显示在这里，也可以继续修改…"
        />
      </label>
      <p v-if="error" class="error">{{ error }}</p>
    </div>
    <template #footer
      ><button class="cancel" @click="store.closeCreative()">取消</button
      ><button class="primary footer-create" :disabled="!canCreate || !modeReady" @click="create">
        加入项目并生成视频
      </button></template
    >
  </BaseModal>
</template>

<style scoped src="./CreativeVideoModal.css"></style>
