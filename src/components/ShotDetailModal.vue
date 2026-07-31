<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { formatTime, useProjectStore } from '../stores/project'

const store = useProjectStore()

// 弹窗内的编辑草稿，保存时才写回 store
const lyricsDraft = ref('')
const scenePromptDraft = ref('')
const shotPromptDraft = ref('')
// 提示词默认只展示折叠预览，点击后展开为可编辑状态
const sceneEditing = ref(false)
const shotEditing = ref(false)

/** 当前选用的视频片段资产 */
const currentAsset = computed(() => {
  const line = store.editingLine
  return line?.shot.assets.find((a) => a.id === line.shot.currentAssetId)
})

/** 当前资产的真实可播放视频（有则在预览框内直接播放） */
const currentVideo = computed(() => {
  const line = store.editingLine
  return line ? store.videoOf(line) : undefined
})

/** 预览图：优先视频片段封面，其次场景底图 */
const previewImage = computed(() => {
  const line = store.editingLine
  return line ? line.shot.imageUrl ?? line.scene.imageUrl : undefined
})

watch(
  () => store.editingLineId,
  () => {
    const line = store.editingLine
    lyricsDraft.value = line?.lyrics ?? ''
    scenePromptDraft.value = line?.scenePrompt ?? ''
    shotPromptDraft.value = line?.shotPrompt ?? ''
    sceneEditing.value = false
    shotEditing.value = false
  },
  { immediate: true },
)

/** 重新生成场景（仅场景提示词） */
const regenScene = () => {
  const line = store.editingLine
  if (!line) return
  store.generateSceneFor(line.id, scenePromptDraft.value)
}

/** 重新生成分镜视频片段（场景 × 分镜提示词 × 出演角色） */
const regenShot = () => {
  const line = store.editingLine
  if (!line) return
  // 重新生成前先持久化当前编辑中的两个提示词
  store.updateScenePrompt(line.id, scenePromptDraft.value)
  store.generateShotFor(line.id, shotPromptDraft.value)
}

const save = () => {
  const line = store.editingLine
  if (line) {
    store.updateLyrics(line.id, lyricsDraft.value)
    store.updateScenePrompt(line.id, scenePromptDraft.value)
    store.updateShotPrompt(line.id, shotPromptDraft.value)
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
          <button class="close-btn" title="关闭" @click="cancel">✕</button>
        </header>

        <div class="modal-body">
          <!-- 上方：生成的分镜内容与资产 -->
          <p class="field-label">分镜预览</p>
          <div class="shot-frame">
            <video v-if="currentVideo" :src="currentVideo" class="shot-img" controls playsinline />
            <img v-else-if="previewImage" :src="previewImage" alt="分镜预览" class="shot-img" />
            <p v-else class="shot-placeholder">尚未生成内容：可先由场景提示词生成场景，再结合分镜提示词与出演角色生成视频片段</p>
            <span v-if="!currentVideo && !store.editingLine.shot.imageUrl && store.editingLine.scene.imageUrl" class="scene-badge">场景底图</span>
            <span v-if="currentAsset && !currentVideo && store.editingLine.shot.imageUrl" class="duration-badge">▶ {{ formatTime(currentAsset.duration) }} · {{ currentAsset.duration }}s</span>
            <div v-if="store.editingLine.scene.status === 'generating' || store.editingLine.shot.status === 'generating'" class="shot-loading">
              <span class="spinner light" />
              <span>{{ store.editingLine.shot.status === 'generating' ? '视频片段生成中（场景 × 分镜 × 角色）…' : '场景生成中…' }}</span>
            </div>
            <!-- 图片框最下面：当前分镜歌词（真实视频播放时不遮挡控制条） -->
            <p v-if="lyricsDraft && !currentVideo" class="lyric-caption">{{ lyricsDraft }}</p>
          </div>

          <div v-if="store.editingLine.shot.assets.length" class="asset-list">
            <div
              v-for="(asset, i) in store.editingLine.shot.assets"
              :key="asset.id"
              class="asset-thumb"
              :class="{ active: asset.id === store.editingLine.shot.currentAssetId }"
              :title="`片段 v${i + 1} · ${asset.duration}s`"
              @click="store.selectShotAsset(store.editingLine.id, asset.id)"
            >
              <video v-if="!asset.coverUrl" :src="asset.videoUrl" preload="metadata" muted />
              <img v-else :src="asset.coverUrl" alt="" />
              <span class="asset-duration">{{ asset.duration }}s</span>
            </div>
          </div>

          <!-- 出演角色（从全局阵容中多选，可为空 = 空镜头） -->
          <div class="prompt-head">
            <p class="field-label">出演角色 <span class="field-tip">从全局阵容中勾选，不选 = 空镜头</span></p>
            <button class="btn-outline regen-btn" @click="store.openLibrary()">👥 管理阵容</button>
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
                <span v-if="store.editingLine.digitalHumanIds.includes(dh.id)" class="pick-mark">✓</span>
              </button>
            </template>
            <span v-else class="cast-none">角色阵容为空，请先到资产库挑选本 MV 的统一角色</span>
          </div>

          <!-- 歌词编辑 -->
          <p class="field-label">歌词（当前分镜）</p>
          <input v-model="lyricsDraft" class="lyrics-input" placeholder="输入这句分镜对应的歌词…" />

          <!-- 场景提示词：默认折叠预览，点击展开编辑后可重新生成场景 -->
          <div class="prompt-head">
            <p class="field-label">场景提示词</p>
            <button class="btn-outline regen-btn" @click="sceneEditing = !sceneEditing">
              {{ sceneEditing ? '收起' : '✏️ 编辑' }}
            </button>
            <button
              class="btn-outline regen-btn"
              :disabled="store.editingLine.scene.status === 'generating' || !scenePromptDraft.trim()"
              @click="regenScene"
            >
              <span v-if="store.editingLine.scene.status === 'generating'" class="spinner" />
              <span v-else>🏞️</span>
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
              {{ shotEditing ? '收起' : '✏️ 编辑' }}
            </button>
            <button
              class="btn-outline regen-btn"
              :disabled="store.editingLine.shot.status === 'generating' || !shotPromptDraft.trim()"
              @click="regenShot"
            >
              <span v-if="store.editingLine.shot.status === 'generating'" class="spinner" />
              <span v-else>🎬</span>
              {{ store.editingLine.shot.assets.length ? '重新生成分镜' : '生成分镜' }}
            </button>
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
          <button class="btn-primary" @click="save">✓ 保存</button>
        </footer>
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

/* 分镜画面框 */
.shot-frame {
  position: relative;
  aspect-ratio: 16 / 9;
  background: #111;
  border-radius: 12px;
  overflow: hidden;
  display: flex;
  align-items: center;
  justify-content: center;
}
.shot-img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}
.shot-placeholder {
  color: #666;
  font-size: 13px;
  padding: 0 24px;
  text-align: center;
}
.shot-loading {
  position: absolute;
  inset: 0;
  background: rgba(0, 0, 0, 0.55);
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: #fff;
  font-size: 13px;
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
.duration-badge {
  position: absolute;
  top: 10px;
  right: 10px;
  background: rgba(0, 0, 0, 0.6);
  color: #fff;
  font-size: 12px;
  padding: 3px 10px;
  border-radius: 12px;
}
.scene-badge {
  position: absolute;
  top: 10px;
  left: 10px;
  background: rgba(0, 0, 0, 0.6);
  color: #fff;
  font-size: 12px;
  padding: 3px 10px;
  border-radius: 12px;
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
  font-weight: 700;
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
  margin-top: 10px;
  flex-wrap: wrap;
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
