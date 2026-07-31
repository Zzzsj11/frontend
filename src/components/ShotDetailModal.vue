<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { DEFAULT_SHOT_OPTIONS, useProjectStore } from '../stores/project'
import type { ShotAsset, ShotGenOptions } from '../types'
import AppIcon from './AppIcon.vue'

const store = useProjectStore()

// 弹窗内的编辑草稿，保存时才写回 store
const lyricsDraft = ref('')
const scenePromptDraft = ref('')
const shotPromptDraft = ref('')
// 提示词默认只展示折叠预览，点击后展开为可编辑状态
const sceneEditing = ref(false)
const shotEditing = ref(false)

// 分镜视频生成参数草稿（清晰度 / 时长 / 画幅），重新生成分镜时生效
const optionsDraft = ref<ShotGenOptions>({ ...DEFAULT_SHOT_OPTIONS })
const resolutionChoices: ShotGenOptions['resolution'][] = ['480p', '720p', '1080p']
const durationChoices = [3, 5, 8, 10, 12]
const ratioChoices: ShotGenOptions['ratio'][] = ['16:9', '9:16', '4:3', '1:1']

// 歌词非中文（不含汉字）且存在译文时，在歌词下方展示中文翻译
const lyricsTranslation = computed(() => {
  const zh = store.editingLine?.lyricsZh?.trim()
  if (!zh || !lyricsDraft.value || /[\u4e00-\u9fff]/.test(lyricsDraft.value)) return undefined
  return zh
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

/** 预览片段的真实可播放视频地址（mock:// 假地址除外，退化为展示封面） */
const previewVideo = computed(() =>
  previewAsset.value && /^(\/|https?:)/.test(previewAsset.value.videoUrl)
    ? previewAsset.value.videoUrl
    : undefined,
)

watch(
  () => store.editingLineId,
  () => {
    const line = store.editingLine
    lyricsDraft.value = line?.lyrics ?? ''
    scenePromptDraft.value = line?.scenePrompt ?? ''
    shotPromptDraft.value = line?.shotPrompt ?? ''
    optionsDraft.value = { ...(line?.shotOptions ?? DEFAULT_SHOT_OPTIONS) }
    sceneEditing.value = false
    shotEditing.value = false
    previewAsset.value = null
  },
  { immediate: true },
)

/** 重新生成场景（仅场景提示词） */
const regenScene = () => {
  const line = store.editingLine
  if (!line) return
  store.generateSceneFor(line.id, scenePromptDraft.value)
}

/** 重新生成分镜视频片段（场景 × 分镜提示词 × 出演角色 × 生成参数） */
const regenShot = () => {
  const line = store.editingLine
  if (!line) return
  // 重新生成前先持久化当前编辑中的两个提示词
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
  <Teleport to="body">
    <div v-if="store.editingLine" class="modal-mask" @click.self="cancel">
      <div class="modal">
        <header class="modal-header">
          <h3>编辑分镜内容</h3>
          <button class="close-btn" title="关闭" @click="cancel"><AppIcon name="close" :size="14" /></button>
        </header>

        <div class="modal-body">
          <!-- 上方：已生成的分镜视频片段（点击缩略图选用并弹出预览） -->
          <p class="field-label">分镜片段 <span class="field-tip">点击缩略图选用并弹出预览视频</span></p>
          <div v-if="store.editingLine.shot.assets.length" class="asset-list">
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
            </div>
          </div>
          <p v-else-if="store.editingLine.shot.status !== 'generating'" class="asset-empty">
            尚未生成内容：可先由场景提示词生成场景，再结合分镜提示词与出演角色生成视频片段
          </p>
          <div v-if="store.editingLine.shot.status === 'generating'" class="asset-generating">
            <span class="spinner" />
            <span>视频片段生成中（场景 × 分镜 × 角色）…</span>
          </div>

          <!-- 出演角色（从全局阵容中多选，可为空 = 空镜头） -->
          <div class="prompt-head">
            <p class="field-label">出演角色 <span class="field-tip">从全局阵容中勾选，不选 = 空镜头</span></p>
            <button class="btn-outline regen-btn" @click="store.openLibrary()">
              <AppIcon name="users" :size="14" />
              管理阵容
            </button>
          </div>
          <div class="cast-row">
            <template v-if="store.castHumans.length">
              <button
                v-for="dh in store.castHumans"
                :key="dh.id"
                class="cast-pick"
                :class="{ active: store.editingLine.digitalHumanIds.includes(dh.id) }"
                @click="store.toggleLineHuman(store.editingLine.id, dh.id)"
              >
                <img :src="dh.avatar" :alt="dh.name" />
                <span>{{ dh.name }}</span>
                <span v-if="store.editingLine.digitalHumanIds.includes(dh.id)" class="pick-mark"><AppIcon name="check" :size="12" /></span>
              </button>
            </template>
            <span v-else class="cast-none">角色阵容为空，请先到资产库挑选本 MV 的统一角色</span>
          </div>

          <!-- 歌词编辑 -->
          <p class="field-label">歌词（当前分镜）</p>
          <input v-model="lyricsDraft" class="lyrics-input" placeholder="输入这句分镜对应的歌词…" />
          <p v-if="lyricsTranslation" class="lyrics-zh-hint">中文翻译：{{ lyricsTranslation }}</p>

          <!-- 场景提示词：默认折叠预览，点击展开编辑后可重新生成场景 -->
          <div class="prompt-head">
            <p class="field-label">场景提示词</p>
            <button class="btn-outline regen-btn" @click="sceneEditing = !sceneEditing">
              <AppIcon v-if="!sceneEditing" name="edit" :size="13" />
              {{ sceneEditing ? '收起' : '编辑' }}
            </button>
            <button
              class="btn-outline regen-btn"
              :disabled="store.editingLine.scene.status === 'generating' || !scenePromptDraft.trim()"
              @click="regenScene"
            >
              <span v-if="store.editingLine.scene.status === 'generating'" class="spinner" />
              <AppIcon v-else name="scene" :size="14" />
              {{ store.editingLine.scene.imageUrl ? '重新生成场景' : '生成场景' }}
            </button>
          </div>
          <div class="scene-row">
            <!-- 场景预览：独立于分镜预览，随时可查看场景底图 -->
            <div class="scene-preview">
              <img
                v-if="store.editingLine.scene.imageUrl"
                :src="store.editingLine.scene.imageUrl"
                alt="场景预览"
              />
              <span v-else class="scene-empty">暂无场景</span>
              <div v-if="store.editingLine.scene.status === 'generating'" class="scene-loading">
                <span class="spinner light" />
              </div>
            </div>
            <textarea
              v-if="sceneEditing"
              v-model="scenePromptDraft"
              class="prompt-input scene-input"
              rows="3"
              placeholder="描述这个分镜的背景场景：环境、光线、色调、氛围…"
            />
            <div v-else class="prompt-preview scene-input" title="点击展开编辑" @click="sceneEditing = true">
              {{ scenePromptDraft || '暂无场景提示词，点击编写…' }}
            </div>
          </div>

          <!-- 分镜提示词：默认折叠预览，点击展开编辑后可重新生成分镜视频片段 -->
          <div class="prompt-head">
            <p class="field-label">分镜提示词</p>
            <button class="btn-outline regen-btn" @click="shotEditing = !shotEditing">
              <AppIcon v-if="!shotEditing" name="edit" :size="13" />
              {{ shotEditing ? '收起' : '编辑' }}
            </button>
            <button
              class="btn-outline regen-btn"
              :disabled="store.editingLine.shot.status === 'generating' || !shotPromptDraft.trim()"
              @click="regenShot"
            >
              <span v-if="store.editingLine.shot.status === 'generating'" class="spinner" />
              <AppIcon v-else name="movie" :size="14" />
              {{ store.editingLine.shot.assets.length ? '重新生成分镜' : '生成分镜' }}
            </button>
          </div>
          <!-- 生成参数：清晰度 / 时长 / 画幅，重新生成分镜时生效 -->
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
          </div>
          <textarea
            v-if="shotEditing"
            v-model="shotPromptDraft"
            class="prompt-input"
            rows="3"
            placeholder="描述镜头运动与角色表演，将与场景、出演角色一起生成视频片段…"
          />
          <div v-else class="prompt-preview" title="点击展开编辑" @click="shotEditing = true">
            {{ shotPromptDraft || '暂无分镜提示词，点击编写…' }}
          </div>
        </div>

        <footer class="modal-footer">
          <button class="btn-cancel" @click="cancel">取消</button>
          <button class="btn-primary" @click="save">
            <AppIcon name="check" :size="14" />
            保存
          </button>
        </footer>
      </div>

      <!-- 分镜片段预览弹层：点击缩略图后弹出播放对应视频 -->
      <div v-if="previewAsset" class="preview-mask" @click.self="closePreview">
        <div class="preview-pop">
          <header class="preview-head">
            <span class="preview-title">
              <AppIcon name="play" :size="13" />
              片段 v{{ previewIndex + 1 }} · {{ previewAsset.duration }}s
            </span>
            <button class="close-btn" title="关闭预览" @click="closePreview"><AppIcon name="close" :size="14" /></button>
          </header>
          <div class="preview-body">
            <video v-if="previewVideo" :src="previewVideo" class="preview-media" controls autoplay playsinline />
            <img v-else-if="previewAsset.coverUrl" :src="previewAsset.coverUrl" alt="片段预览" class="preview-media" />
            <p v-else class="preview-placeholder">该片段暂无可播放视频（mock 假数据）</p>
            <!-- 预览最下面：当前分镜歌词（非中文歌词附中文翻译；真实视频播放时不遮挡控制条） -->
            <div v-if="lyricsDraft && !previewVideo" class="lyric-caption">
              <p class="cap-line">{{ lyricsDraft }}</p>
              <p v-if="lyricsTranslation" class="cap-zh">{{ lyricsTranslation }}</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.modal-mask {
  position: fixed;
  inset: 0;
  z-index: 100;
  background: rgba(0, 0, 0, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
}
.modal {
  width: 620px;
  max-width: 100%;
  max-height: 92vh;
  background: #fff;
  border-radius: 16px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.25);
}
.modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 18px 22px;
  border-bottom: 1px solid var(--border);
}
.modal-header h3 {
  margin: 0;
  font-size: 17px;
}
.close-btn {
  border: none;
  background: transparent;
  font-size: 16px;
  color: var(--text-secondary);
  cursor: pointer;
}
.close-btn:hover {
  color: var(--text);
}
.modal-body {
  padding: 16px 22px;
  overflow-y: auto;
}
.field-label {
  margin: 14px 0 8px;
  font-size: 13px;
  font-weight: 700;
  color: var(--text);
}
.field-label:first-child {
  margin-top: 0;
}

/* 分镜片段预览弹层 */
.preview-mask {
  position: fixed;
  inset: 0;
  z-index: 110;
  background: rgba(0, 0, 0, 0.6);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
}
.preview-pop {
  width: 720px;
  max-width: 100%;
  background: #fff;
  border-radius: 14px;
  overflow: hidden;
  box-shadow: 0 24px 70px rgba(0, 0, 0, 0.35);
  display: flex;
  flex-direction: column;
}
.preview-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border);
}
.preview-title {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 14px;
  font-weight: 700;
  color: var(--text);
}
.preview-body {
  position: relative;
  aspect-ratio: 16 / 9;
  background: #111;
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
/* 非中文歌词的中文翻译 */
.lyric-caption .cap-zh {
  margin: 4px 0 0;
  font-size: 13px;
  opacity: 0.85;
}

/* 出演角色行 */
.cast-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 8px 12px;
}
.cast-pick {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border: 1px solid var(--border-dark);
  border-radius: 18px;
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
  border-radius: 6px;
  object-fit: cover;
}
.cast-pick:hover {
  border-color: var(--primary);
}
.cast-pick.active {
  border-color: var(--primary);
  background: var(--primary-light);
  color: var(--primary);
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
.field-tip {
  font-weight: 400;
  font-size: 12px;
  color: var(--text-secondary);
  margin-left: 6px;
}

/* 资产列表 */
.asset-list {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.asset-empty {
  margin: 0;
  border: 1px dashed var(--border-dark);
  border-radius: 10px;
  padding: 14px 16px;
  font-size: 13px;
  color: var(--text-secondary);
}
.asset-generating {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 8px;
  font-size: 13px;
  color: var(--text-secondary);
}
.asset-thumb {
  position: relative;
  width: 96px;
  aspect-ratio: 16 / 9;
  border-radius: 8px;
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
  border-radius: 6px;
}
/* 悬停缩略图时的播放角标，提示可弹出预览 */
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

/* 场景预览 */
.scene-row {
  display: flex;
  gap: 10px;
  align-items: stretch;
}
.scene-preview {
  position: relative;
  width: 150px;
  flex-shrink: 0;
  aspect-ratio: 16 / 9;
  align-self: flex-start;
  background: #111;
  border-radius: 10px;
  overflow: hidden;
  display: flex;
  align-items: center;
  justify-content: center;
}
.scene-preview img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}
.scene-empty {
  color: #666;
  font-size: 12px;
}
.scene-loading {
  position: absolute;
  inset: 0;
  background: rgba(0, 0, 0, 0.55);
  display: flex;
  align-items: center;
  justify-content: center;
}
.scene-input {
  flex: 1;
}

/* 输入框 */
.lyrics-input,
.prompt-input {
  width: 100%;
  border: 1px solid var(--border-dark);
  border-radius: 10px;
  padding: 10px 12px;
  font-size: 14px;
  font-family: inherit;
  color: var(--text);
  outline: none;
  transition: border-color 0.15s, box-shadow 0.15s;
}
.lyrics-input:focus,
.prompt-input:focus {
  border-color: var(--primary);
  box-shadow: 0 0 0 2px rgba(255, 90, 44, 0.12);
}
/* 非中文歌词的中文翻译提示 */
.lyrics-zh-hint {
  margin: 6px 2px 0;
  font-size: 12px;
  color: var(--text-secondary);
}
.prompt-input {
  resize: vertical;
  min-height: 72px;
}
.prompt-head {
  display: flex;
  align-items: center;
  gap: 8px;
  justify-content: flex-end;
}
.prompt-head .field-label {
  margin-right: auto;
}
.regen-btn {
  padding: 5px 12px;
}

/* 生成参数选择（清晰度 / 时长 / 画幅） */
.gen-options {
  display: flex;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
  margin: 2px 0 10px;
}
.opt-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.opt-label {
  font-size: 12px;
  color: var(--text-secondary);
}
.opt-select {
  border: 1px solid var(--border-dark);
  border-radius: 8px;
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

/* 提示词折叠预览（默认只展示 3 行，点击展开编辑） */
.prompt-preview {
  border: 1px solid var(--border);
  border-radius: 10px;
  background: #fafafa;
  padding: 10px 12px;
  font-size: 13px;
  line-height: 1.6;
  color: var(--text-secondary);
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
  overflow-wrap: break-word;
  cursor: pointer;
  transition: border-color 0.15s;
}
.prompt-preview:hover {
  border-color: var(--primary);
}

/* 底部 */
.modal-footer {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  padding: 14px 22px;
  border-top: 1px solid var(--border);
}
.btn-cancel {
  border: 1px solid var(--border-dark);
  border-radius: 20px;
  background: #fff;
  color: var(--text);
  font-size: 14px;
  padding: 9px 24px;
  cursor: pointer;
  transition: border-color 0.15s;
}
.btn-cancel:hover {
  border-color: var(--text-secondary);
}
</style>
