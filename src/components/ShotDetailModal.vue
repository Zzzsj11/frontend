<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { DEFAULT_SHOT_OPTIONS, useProjectStore } from '../stores/project'
import type { ShotAsset, ShotGenOptions } from '../types'
import AppIcon from './AppIcon.vue'
import BaseModal from './base/BaseModal.vue'
import CharacterPortrait from './CharacterPortrait.vue'
import ImageZoom from './ImageZoom.vue'
import { confirmDialog } from '../composables/useConfirmDialog'
import { normalizeShotOptions, VIDEO_DURATION_CHOICES } from '../mediaConstraints'
import { IMAGE_MODEL_OPTIONS, VIDEO_MODEL_OPTIONS, loadGenerationModels } from '../generationModels'

const store = useProjectStore()
void loadGenerationModels()

// 弹窗内的编辑草稿，保存时才写回 store
const lyricsDraft = ref('')
const scenePromptDraft = ref('')
const shotPromptDraft = ref('')

// 当前展开的调整面板：默认全部折叠，只展示人物 / 分镜 / 场景三个预览
type TabKey = 'cast' | 'shot' | 'scene'
const activeTab = ref<TabKey | null>(null)

// 分镜视频生成参数草稿（清晰度 / 时长 / 画幅 / 模型），重新生成分镜时生效
const optionsDraft = ref<ShotGenOptions>({ ...DEFAULT_SHOT_OPTIONS })
const resolutionChoices: ShotGenOptions['resolution'][] = ['480p', '720p', '1080p']
const durationChoices = VIDEO_DURATION_CHOICES
const ratioChoices: ShotGenOptions['ratio'][] = ['16:9', '9:16', '4:3', '1:1']

// 歌词非中文（不含汉字）且存在译文时，在歌词下方展示中文翻译
const lyricsTranslation = computed(() => {
  const zh = store.editingLine?.lyricsZh?.trim()
  if (!zh || !lyricsDraft.value || /[\u4e00-\u9fff]/.test(lyricsDraft.value)) return undefined
  return zh
})
const isGeneral = computed(() => store.editingLine?.source === 'general')
// ASS 大纲已生成的行，角色由大纲分配不可手动修改
const castLocked = computed(
  () =>
    store.activeStoryboardType === 'ass' &&
    store.editingLine?.shotOptions?.outlineStatus !== undefined &&
    store.editingLine?.shotOptions?.outlineStatus !== 'pending' &&
    store.editingLine?.shotOptions?.outlineStatus !== 'failed',
)

// 人物预览：当前分镜出演角色（空 = 空镜头）
const castOfLine = computed(() => {
  const line = store.editingLine
  return line ? store.lineHumans(line) : []
})

// 分镜预览：当前选用片段的视频 / 封面
const shotVideo = computed(() => {
  const line = store.editingLine
  return line ? store.videoOf(line) : undefined
})
const shotCover = computed(() => {
  const line = store.editingLine
  return line ? store.coverOf(line) : undefined
})
const shotOriginalCover = computed(() => {
  const line = store.editingLine
  return (
    line?.shot.assets.find((asset) => asset.id === line.shot.currentAssetId)?.originalCoverUrl ||
    shotCover.value
  )
})

/** 弹出预览中的视频片段（点击缩略图时选用并预览） */
const previewAsset = ref<ShotAsset | null>(null)
const previewIndex = ref(0)

const pickAsset = (asset: ShotAsset, index: number) => {
  const line = store.editingLine
  if (!line) return
  store.selectShotAsset(line.id, asset.id)
  previewAsset.value = asset
  previewIndex.value = index
}

const closePreview = () => {
  previewAsset.value = null
}

// 点击分镜预览：选中并展开分镜调整面板；历史片段仍可在展开后的列表中点击预览
const onShotPreviewClick = () => {
  activeTab.value = 'shot'
}

/** 预览片段的真实可播放视频地址（mock:// 假地址除外，退化为展示封面） */
const previewVideo = computed(() =>
  previewAsset.value && /^(\/|https?:)/.test(previewAsset.value.videoUrl)
    ? previewAsset.value.videoUrl
    : undefined,
)

watch(
  () => [store.editingLineId, store.editingTab] as const,
  () => {
    const line = store.editingLine
    lyricsDraft.value = line?.lyrics ?? ''
    scenePromptDraft.value = line?.scenePrompt ?? ''
    shotPromptDraft.value = line?.shotPrompt ?? ''
    optionsDraft.value = normalizeShotOptions(line?.shotOptions ?? DEFAULT_SHOT_OPTIONS)
    activeTab.value = store.editingTab
    previewAsset.value = null
  },
  { immediate: true },
)

/** 生成 / 重新生成场景（仅场景提示词）；已有场景图时二次确认（会被覆盖） */
const regenScene = async () => {
  const line = store.editingLine
  if (!line) return
  if (
    line.scene.imageUrl &&
    !(await confirmDialog({
      title: '重新生成场景',
      message: '确定重新生成场景？当前场景图将被覆盖。',
      confirmText: '重新生成',
    }))
  )
    return
  store.generateSceneFor(line.id, scenePromptDraft.value, { ...optionsDraft.value })
}

/** 生成 / 重新生成分镜视频片段（场景 × 分镜提示词 × 出演角色 × 生成参数）；已有片段时二次确认 */
const regenShot = async () => {
  const line = store.editingLine
  if (!line) return
  if (
    line.shot.assets.length &&
    !(await confirmDialog({
      title: '重新生成视频',
      message: '确定重新生成视频片段？将新增一个视频版本。',
      confirmText: '重新生成',
    }))
  )
    return
  // 重新生成前先持久化当前编辑中的场景提示词
  store.updateScenePrompt(line.id, scenePromptDraft.value)
  store.generateShotFor(line.id, shotPromptDraft.value, { ...optionsDraft.value })
}

const save = () => {
  const line = store.editingLine
  if (line) {
    store.updateLyrics(line.id, lyricsDraft.value)
    store.updateScenePrompt(line.id, scenePromptDraft.value)
    store.updateShotPrompt(line.id, shotPromptDraft.value)
    store.updateShotOptions(line.id, { ...optionsDraft.value })
  }
  store.closeEditor()
}

const cancel = () => store.closeEditor()
</script>

<template>
  <BaseModal :open="!!store.editingLine" width="620px" aria-label="编辑视频内容" @close="cancel">
    <template #title>编辑视频内容</template>
    <template v-if="store.editingLine">
      <div class="modal-body">
        <p class="body-tip">点击任一预览下方的标签，展开调整对应的参数与提示词</p>

        <!-- 三个预览：人物 / 分镜 / 场景 -->
        <div class="preview-cards">
          <!-- 人物 -->
          <div class="pcard" :class="{ open: activeTab === 'cast' }">
            <div class="pcard-media" title="点击展开人物调整" @click="activeTab = 'cast'">
              <div v-if="castOfLine.length" class="pcard-avatars">
                <CharacterPortrait
                  v-for="dh in castOfLine"
                  :key="dh.id"
                  :src="dh.avatar"
                  :alt="dh.name"
                  :title="dh.name"
                />
              </div>
              <span v-else class="pcard-empty"><AppIcon name="user" :size="24" />空镜头</span>
            </div>
            <button
              class="pcard-tab"
              :class="{ active: activeTab === 'cast' }"
              @click="activeTab = 'cast'"
            >
              <AppIcon name="users" :size="13" />
              人物
              <span class="pcard-count">{{ castOfLine.length }}</span>
            </button>
          </div>

          <!-- 视频预览 -->
          <div class="pcard" :class="{ open: activeTab === 'shot' }">
            <div class="pcard-media" title="点击播放当前片段" @click="onShotPreviewClick">
              <img v-if="shotCover" :src="shotCover" alt="视频预览" />
              <video v-else-if="shotVideo" :src="shotVideo" preload="metadata" muted />
              <span v-else class="pcard-empty"><AppIcon name="movie" :size="24" />暂无视频</span>
              <span v-if="shotVideo || shotCover" class="pcard-play"
                ><AppIcon name="play" :size="16"
              /></span>
              <ImageZoom :src="shotOriginalCover" alt="视频封面原图预览" />
              <span v-if="store.editingLine.shot.assets.length > 1" class="pcard-badge">
                {{ store.editingLine.shot.assets.length }} 版
              </span>
              <div v-if="store.editingLine.shot.status === 'generating'" class="pcard-loading">
                <span class="spinner light" />
              </div>
              <div
                v-else-if="store.editingLine.shot.status === 'failed'"
                class="pcard-failed"
                :title="store.editingLine.shot.error || '未知原因'"
              >
                <AppIcon name="alert" :size="18" />
                <span>视频生成失败</span>
              </div>
            </div>
            <button
              class="pcard-tab"
              :class="{ active: activeTab === 'shot' }"
              @click="activeTab = 'shot'"
            >
              <AppIcon name="movie" :size="13" />
              视频
            </button>
          </div>

          <!-- 场景预览 -->
          <div class="pcard" :class="{ open: activeTab === 'scene' }">
            <div class="pcard-media" title="点击展开场景调整" @click="activeTab = 'scene'">
              <img
                v-if="store.editingLine.scene.imageUrl"
                :src="store.editingLine.scene.imageUrl"
                alt="场景预览"
              />
              <span v-else class="pcard-empty"><AppIcon name="scene" :size="24" />暂无场景</span>
              <ImageZoom :src="store.editingLine.scene.originalImageUrl" alt="场景原图预览" />
              <div v-if="store.editingLine.scene.status === 'generating'" class="pcard-loading">
                <span class="spinner light" />
              </div>
              <div
                v-else-if="store.editingLine.scene.status === 'failed'"
                class="pcard-failed"
                :title="store.editingLine.scene.error || '未知原因'"
              >
                <AppIcon name="alert" :size="18" />
                <span>场景图生成失败</span>
              </div>
            </div>
            <button
              class="pcard-tab"
              :class="{ active: activeTab === 'scene' }"
              @click="activeTab = 'scene'"
            >
              <AppIcon name="scene" :size="13" />
              场景
            </button>
          </div>
        </div>

        <!-- 人物调整面板 -->
        <div v-if="activeTab === 'cast'" class="tab-panel">
          <div class="panel-head">
            <span class="panel-title">出演角色</span>
            <button class="btn-outline regen-btn" @click="store.openLibrary()">
              <AppIcon name="users" :size="14" />
              管理阵容
            </button>
          </div>
          <p v-if="castLocked" class="cast-locked-hint">角色由大纲分配，不支持手动修改</p>
          <div class="cast-row">
            <template v-if="store.castHumans.length">
              <button
                v-for="dh in store.castHumans"
                :key="dh.id"
                class="cast-pick"
                :class="{ active: store.editingLine.digitalHumanIds.includes(dh.id) }"
                :disabled="castLocked"
                :title="castLocked ? '角色由大纲分配，不支持修改' : undefined"
                @click="!castLocked && store.toggleLineHuman(store.editingLine.id, dh.id)"
              >
                <CharacterPortrait :src="dh.avatar" :alt="dh.name" />
                <span>{{ dh.name }}</span>
                <span v-if="store.editingLine.digitalHumanIds.includes(dh.id)" class="pick-mark"
                  ><AppIcon name="check" :size="12"
                /></span>
              </button>
            </template>
            <span v-else class="cast-none">角色阵容为空，请先到资产库挑选本 MV 的统一角色</span>
          </div>
        </div>

        <!-- 分镜调整面板 -->
        <div v-if="activeTab === 'shot'" class="tab-panel">
          <template v-if="!isGeneral">
            <p class="panel-title">歌词（当前视频）</p>
            <input
              v-model="lyricsDraft"
              class="lyrics-input"
              placeholder="输入这段视频对应的歌词…"
            />
            <p v-if="lyricsTranslation" class="lyrics-zh-hint">中文翻译：{{ lyricsTranslation }}</p>
          </template>
          <p v-else class="general-shot-tip">
            {{ store.editingLine.shotType === 'empty' ? '空镜' : '人物镜' }}
            · 规划时长 {{ store.editingLine.plannedDuration ?? 0 }} 秒
          </p>

          <template v-if="store.editingLine.shot.assets.length">
            <p class="panel-title mt">已生成片段 <span class="field-tip">点击选用并预览</span></p>
            <div class="asset-list">
              <div
                v-for="(asset, i) in store.editingLine.shot.assets"
                :key="asset.id"
                class="asset-thumb"
                :class="{ active: asset.id === store.editingLine.shot.currentAssetId }"
                :title="`片段 v${i + 1} · ${asset.duration}s，点击选用并预览`"
                @click="pickAsset(asset, i)"
              >
                <video v-if="!asset.coverUrl" :src="asset.videoUrl" preload="metadata" muted />
                <img v-else :src="asset.coverUrl" alt="" />
                <span class="asset-play"><AppIcon name="play" :size="12" /></span>
                <span class="asset-duration">{{ asset.duration }}s</span>
                <ImageZoom
                  :src="asset.originalCoverUrl || asset.coverUrl"
                  :alt="`片段 v${i + 1} 原图预览`"
                />
              </div>
            </div>
          </template>

          <!-- 生成参数：清晰度 / 时长 / 画幅 / 模型，重新生成分镜时生效 -->
          <p class="panel-title mt">生成参数</p>
          <div class="gen-options">
            <label class="opt-item">
              <span class="opt-label">清晰度</span>
              <select v-model="optionsDraft.resolution" class="opt-select">
                <option v-for="r in resolutionChoices" :key="r" :value="r">{{ r }}</option>
              </select>
            </label>
            <label class="opt-item">
              <span class="opt-label">时长</span>
              <select v-model.number="optionsDraft.duration" class="opt-select">
                <option v-for="d in durationChoices" :key="d" :value="d">{{ d }}s</option>
              </select>
            </label>
            <label class="opt-item">
              <span class="opt-label">画幅</span>
              <select v-model="optionsDraft.ratio" class="opt-select">
                <option v-for="r in ratioChoices" :key="r" :value="r">{{ r }}</option>
              </select>
            </label>
            <label class="opt-item">
              <span class="opt-label">视频模型</span>
              <select v-model="optionsDraft.videoModel" class="opt-select" disabled>
                <option v-for="item in VIDEO_MODEL_OPTIONS" :key="item.value" :value="item.value">
                  {{ item.label }}
                </option>
              </select>
            </label>
            <label class="opt-item">
              <span class="opt-label">图片模型</span>
              <select v-model="optionsDraft.imageModel" class="opt-select" disabled>
                <option v-for="item in IMAGE_MODEL_OPTIONS" :key="item.value" :value="item.value">
                  {{ item.label }}
                </option>
              </select>
            </label>
          </div>

          <p class="panel-title mt">视频提示词</p>
          <div class="prompt-editor">
            <textarea
              v-model="shotPromptDraft"
              class="prompt-input prompt-shot"
              rows="6"
              placeholder="描述镜头运动与角色表演，将与场景、出演角色一起生成视频片段…"
            />
            <p
              v-if="store.editingLine.shot.status === 'failed'"
              class="gen-error"
              :title="store.editingLine.shot.error"
            >
              上次生成失败：{{ store.editingLine.shot.error || '未知原因' }}
            </p>
            <button
              class="btn-outline prompt-action"
              :disabled="store.editingLine.shot.status === 'generating' || !shotPromptDraft.trim()"
              @click="regenShot"
            >
              <span v-if="store.editingLine.shot.status === 'generating'" class="spinner" />
              <AppIcon v-else name="movie" :size="14" />
              {{ store.editingLine.shot.assets.length ? '重新生成视频' : '生成视频' }}
            </button>
          </div>
        </div>

        <!-- 场景调整面板 -->
        <div v-if="activeTab === 'scene'" class="tab-panel">
          <p class="panel-title">生成参数</p>
          <div class="gen-options scene-gen-options">
            <label class="opt-item">
              <span class="opt-label">清晰度</span>
              <select v-model="optionsDraft.resolution" class="opt-select">
                <option v-for="r in resolutionChoices" :key="r" :value="r">{{ r }}</option>
              </select>
            </label>
            <label class="opt-item">
              <span class="opt-label">画幅</span>
              <select v-model="optionsDraft.ratio" class="opt-select">
                <option v-for="r in ratioChoices" :key="r" :value="r">{{ r }}</option>
              </select>
            </label>
            <label class="opt-item">
              <span class="opt-label">图片模型</span>
              <select v-model="optionsDraft.imageModel" class="opt-select" disabled>
                <option v-for="item in IMAGE_MODEL_OPTIONS" :key="item.value" :value="item.value">
                  {{ item.label }}
                </option>
              </select>
            </label>
          </div>
          <p class="panel-title">场景提示词</p>
          <div class="prompt-editor">
            <textarea
              v-model="scenePromptDraft"
              class="prompt-input"
              rows="3"
              placeholder="描述这段视频的背景场景：环境、光线、色调、氛围…"
            />
            <p
              v-if="store.editingLine.scene.status === 'failed'"
              class="gen-error"
              :title="store.editingLine.scene.error"
            >
              上次生成失败：{{ store.editingLine.scene.error || '未知原因' }}
            </p>
            <button
              class="btn-outline prompt-action"
              :disabled="
                store.editingLine.scene.status === 'generating' || !scenePromptDraft.trim()
              "
              @click="regenScene"
            >
              <span v-if="store.editingLine.scene.status === 'generating'" class="spinner" />
              <AppIcon v-else name="scene" :size="14" />
              {{ store.editingLine.scene.imageUrl ? '重新生成场景' : '生成场景' }}
            </button>
          </div>
        </div>
      </div>
    </template>
    <template v-if="store.editingLine" #footer>
      <button class="btn-cancel" @click="cancel">取消</button>
      <button class="btn-primary" @click="save">
        <AppIcon name="check" :size="14" />
        保存
      </button>
    </template>
  </BaseModal>

  <!-- 分镜片段预览弹层：点击缩略图后弹出播放对应视频 -->
  <BaseModal
    :open="!!previewAsset"
    level="nested"
    width="720px"
    aria-label="片段预览"
    @close="closePreview"
  >
    <template #title>
      <AppIcon name="play" :size="13" />
      片段 v{{ previewIndex + 1 }} · {{ previewAsset?.duration }}s
    </template>
    <template v-if="previewAsset">
      <div class="preview-body">
        <video
          v-if="previewVideo"
          :src="previewVideo"
          class="preview-media"
          controls
          autoplay
          playsinline
        />
        <img
          v-else-if="previewAsset?.coverUrl"
          :src="previewAsset.coverUrl"
          alt="片段预览"
          class="preview-media"
        />
        <p v-else class="preview-placeholder">该片段暂无可播放视频（mock 假数据）</p>
        <!-- 预览最下面：当前分镜歌词（非中文歌词附中文翻译；真实视频播放时不遮挡控制条） -->
        <div v-if="lyricsDraft && !previewVideo" class="lyric-caption">
          <p class="cap-line">{{ lyricsDraft }}</p>
          <p v-if="lyricsTranslation" class="cap-zh">{{ lyricsTranslation }}</p>
        </div>
      </div>
    </template>
  </BaseModal>
</template>

<style scoped>
.modal-body {
  padding: 16px 22px 20px;
  overflow-y: auto;
}
.body-tip {
  margin: 0 0 14px;
  font-size: var(--font-sm);
  color: var(--text-secondary);
}

/* 三个预览卡片：人物 / 分镜 / 场景 */
.preview-cards {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
}
.pcard {
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  overflow: hidden;
  transition:
    border-color 0.15s,
    box-shadow 0.15s;
}
.pcard.open {
  border-color: var(--primary);
  box-shadow: 0 0 0 1px var(--primary);
}
.pcard-media {
  position: relative;
  aspect-ratio: 4 / 3;
  background: var(--surface-dark);
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  overflow: hidden;
}
.pcard-media > img,
.pcard-media > video {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}
.pcard-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  color: var(--text-secondary);
  font-size: var(--font-sm);
}
/* 人物预览：出演角色头像并排（多个时轻微重叠） */
.pcard-avatars {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 8px;
  gap: 0;
}
.pcard-avatars img {
  width: 96px;
  height: 54px;
  border-radius: var(--radius-sm);
  object-fit: contain;
  border: 2px solid #fff;
  margin-left: -12px;
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.3);
}
.pcard-avatars img:first-child {
  margin-left: 0;
}
/* 分镜预览的播放角标 */
.pcard-play {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  background: rgba(0, 0, 0, 0.28);
  opacity: 0;
  transition: opacity 0.15s;
}
.pcard-media:hover .pcard-play {
  opacity: 1;
}
.pcard-badge {
  position: absolute;
  right: 5px;
  top: 5px;
  background: rgba(0, 0, 0, 0.6);
  color: #fff;
  font-size: 10px;
  padding: 1px 6px;
  border-radius: var(--radius-sm);
}
.pcard-loading {
  position: absolute;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
}
.pcard-failed {
  position: absolute;
  inset: 0;
  background: rgba(198, 40, 40, 0.62);
  color: #fff;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 4px;
  font-size: var(--font-sm);
  font-weight: 600;
}
.gen-error {
  margin: 0;
  padding: 8px 12px 0;
  color: var(--danger-active);
  font-size: var(--font-sm);
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}
/* 每张卡片下方的 tab 标签，点击展开对应参数 */
.pcard-tab {
  width: 100%;
  border: none;
  border-top: 1px solid var(--border);
  background: #fff;
  color: var(--text);
  font-size: 13px;
  font-weight: 600;
  padding: 8px 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  cursor: pointer;
  transition:
    background 0.15s,
    color 0.15s;
}
.pcard-tab:hover {
  color: var(--primary);
}
.pcard-tab.active {
  background: var(--primary);
  color: #fff;
}
.pcard-count {
  min-width: 16px;
  height: 16px;
  padding: 0 4px;
  border-radius: var(--radius-sm);
  background: var(--primary-light);
  color: var(--primary);
  font-size: 11px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}
.pcard-tab.active .pcard-count {
  background: rgba(255, 255, 255, 0.25);
  color: #fff;
}

/* 展开的调整面板 */
.tab-panel {
  margin-top: 14px;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  padding: 14px 16px;
  background: var(--surface-muted);
  animation: panelIn 0.18s ease;
}
@keyframes panelIn {
  from {
    opacity: 0;
    transform: translateY(-4px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}
.panel-title {
  margin: 0 0 8px;
  font-size: 13px;
  font-weight: 700;
  color: var(--text);
}
.panel-title.mt {
  margin-top: 14px;
}
.panel-head {
  display: flex;
  align-items: center;
  gap: 8px;
  justify-content: flex-end;
}
.panel-head .panel-title {
  margin: 0 auto 0 0;
}
.panel-head.mt {
  margin-top: 14px;
}
.regen-btn {
  padding: 5px 12px;
}
.field-tip {
  font-weight: 400;
  font-size: var(--font-sm);
  color: var(--text-secondary);
  margin-left: 6px;
}

/* 出演角色行 */
.cast-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.cast-pick {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border: 1px solid var(--border-dark);
  border-radius: var(--radius-pill);
  background: #fff;
  color: var(--text);
  font-size: 13px;
  padding: 3px 10px 3px 4px;
  cursor: pointer;
  transition: all 0.15s;
}
.cast-pick img {
  width: 24px;
  height: 32px;
  border-radius: var(--radius-sm);
  object-fit: cover;
}
.cast-pick:hover:not(:disabled) {
  border-color: var(--primary);
}
.cast-pick.active {
  border-color: var(--primary);
  background: var(--primary-light);
  color: var(--primary);
}
.cast-pick:disabled {
  cursor: default;
  opacity: 0.7;
}
.cast-locked-hint {
  margin: 0 0 8px;
  font-size: 12px;
  color: var(--text-secondary);
  background: #f5f3f0;
  padding: 5px 10px;
  border-radius: var(--radius-sm);
}
.pick-mark {
  display: inline-flex;
  align-items: center;
  color: var(--primary);
}
.cast-none {
  font-size: 13px;
  color: var(--text-secondary);
}

/* 已生成片段缩略图列表 */
.asset-list {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.asset-thumb {
  position: relative;
  width: 96px;
  aspect-ratio: 16 / 9;
  border-radius: var(--radius-sm);
  border: 2px solid transparent;
  overflow: hidden;
  cursor: pointer;
  transition: border-color 0.15s;
}
.asset-thumb img,
.asset-thumb video {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}
.asset-duration {
  position: absolute;
  right: 3px;
  bottom: 3px;
  background: rgba(0, 0, 0, 0.65);
  color: #fff;
  font-size: 10px;
  padding: 1px 5px;
  border-radius: var(--radius-sm);
}
.asset-play {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  background: rgba(0, 0, 0, 0.35);
  opacity: 0;
  transition: opacity 0.15s;
}
.asset-thumb:hover .asset-play {
  opacity: 1;
}
.asset-thumb:hover {
  border-color: rgba(255, 90, 44, 0.4);
}
.asset-thumb.active {
  border-color: var(--primary);
}

/* 输入框 */
.lyrics-input,
.prompt-input {
  width: 100%;
  border: 1px solid var(--border-dark);
  border-radius: var(--radius-sm);
  padding: 10px 12px;
  font-size: var(--font-md);
  font-family: inherit;
  color: var(--text);
  outline: none;
  transition:
    border-color 0.15s,
    box-shadow 0.15s;
}
.lyrics-input:focus,
.prompt-input:focus {
  border-color: var(--primary);
  box-shadow: 0 0 0 2px rgba(255, 90, 44, 0.12);
}
.lyrics-zh-hint {
  margin: 6px 2px 0;
  font-size: var(--font-sm);
  color: var(--text-secondary);
}
.prompt-input {
  resize: vertical;
  min-height: 72px;
  display: block;
}
.prompt-editor {
  display: flex;
  flex-direction: column;
  border: 1px solid var(--border-dark);
  border-radius: var(--radius-sm);
  background: #fff;
  overflow: hidden;
  transition:
    border-color 0.15s,
    box-shadow 0.15s;
}
.prompt-editor:focus-within {
  border-color: var(--primary);
  box-shadow: 0 0 0 2px rgba(255, 90, 44, 0.12);
}
.prompt-editor .prompt-input {
  border: none;
  border-radius: 0;
  box-shadow: none;
}
.prompt-editor .prompt-input:focus {
  border-color: transparent;
  box-shadow: none;
}
.prompt-action {
  align-self: flex-end;
  flex-shrink: 0;
  margin: 0 12px 12px;
  padding: 6px 12px;
  background: #fff;
  box-shadow: 0 2px 7px rgba(0, 0, 0, 0.06);
}
/* 分镜提示词框加大，方便编写较长的镜头描述 */
.prompt-input.prompt-shot {
  min-height: 132px;
}

/* 生成参数选择（清晰度 / 时长 / 画幅 / 模型） */
.gen-options {
  display: flex;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
  margin-top: 10px;
}
.opt-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.opt-label {
  font-size: var(--font-sm);
  color: var(--text-secondary);
}
.opt-select {
  border: 1px solid var(--border-dark);
  border-radius: var(--radius-sm);
  background: #fff;
  color: var(--text);
  font-size: 13px;
  font-family: inherit;
  padding: 5px 8px;
  cursor: pointer;
  outline: none;
  transition: border-color 0.15s;
}
.opt-select:hover,
.opt-select:focus {
  border-color: var(--primary);
}

/* 底部 */
.btn-cancel {
  border: 1px solid var(--border-dark);
  border-radius: var(--radius-pill);
  background: #fff;
  color: var(--text);
  font-size: var(--font-md);
  padding: 9px 24px;
  cursor: pointer;
  transition: border-color 0.15s;
}
.btn-cancel:hover {
  border-color: var(--text-secondary);
}

/* 分镜片段预览弹层 */
.preview-body {
  position: relative;
  aspect-ratio: 16 / 9;
  background: var(--surface-dark);
  display: flex;
  align-items: center;
  justify-content: center;
}
.preview-media {
  width: 100%;
  height: 100%;
  object-fit: contain;
}
img.preview-media {
  object-fit: cover;
}
.preview-placeholder {
  color: #666;
  font-size: 13px;
  padding: 0 24px;
  text-align: center;
}
.lyric-caption {
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  margin: 0;
  padding: 18px 16px 10px;
  text-align: center;
  color: #fff;
  font-size: 15px;
  text-shadow: 0 1px 4px rgba(0, 0, 0, 0.8);
  background: linear-gradient(transparent, rgba(0, 0, 0, 0.55));
}
.lyric-caption .cap-line {
  margin: 0;
}
.lyric-caption .cap-zh {
  margin: 4px 0 0;
  font-size: 13px;
  opacity: 0.85;
}
.pcard-avatars .character-portrait {
  width: 96px;
  height: 54px;
  margin-left: -12px;
  border: 2px solid #fff;
  border-radius: var(--radius-sm);
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.3);
}
.pcard-avatars .character-portrait:first-child {
  margin-left: 0;
}
.cast-pick .character-portrait {
  width: 24px;
  height: 32px;
  border-radius: var(--radius-sm);
}
</style>
