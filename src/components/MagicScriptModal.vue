<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useProjectStore } from '../stores/project'
import AppIcon from './AppIcon.vue'
import type { ShotGenOptions } from '../types'
import { DEFAULT_IMAGE_MODEL, DEFAULT_VIDEO_MODEL, IMAGE_MODEL_OPTIONS, VIDEO_MODEL_OPTIONS } from '../generationModels'

const store = useProjectStore()

// 表单草稿
const songId = ref('')
const assFile = ref<File | null>(null)
const selectedHumanIds = ref<string[]>([])
const extraRequirement = ref('')
const ratio = ref<ShotGenOptions['ratio']>('16:9')
const resolution = ref<ShotGenOptions['resolution']>('720p')
const imageModel = ref(DEFAULT_IMAGE_MODEL)
const videoModel = ref(DEFAULT_VIDEO_MODEL)

const assInputRef = ref<HTMLInputElement>()

const canSubmit = computed(() => songId.value.trim() !== '' && assFile.value !== null)

// 每次打开弹窗重置表单
watch(
  () => store.magicOpen,
  (open) => {
    if (open) resetForm()
  },
)

const resetForm = () => {
  songId.value = ''
  assFile.value = null
  selectedHumanIds.value = [...store.castIds]
  extraRequirement.value = ''
  ratio.value = '16:9'
  resolution.value = '720p'
  imageModel.value = DEFAULT_IMAGE_MODEL
  videoModel.value = DEFAULT_VIDEO_MODEL
}

// ---------- ass 文件 ----------
const pickAss = (files: FileList | null) => {
  const file = files?.[0]
  if (!file) return
  assFile.value = file
  store.magicError = null
  const codes = file.name.match(/(?<!\d)\d{5,}(?!\d)/g) ?? []
  songId.value = codes.length === 1 ? codes[0] : ''
}
const onAssChange = (e: Event) => {
  pickAss((e.target as HTMLInputElement).files)
  ;(e.target as HTMLInputElement).value = ''
}
const onAssDrop = (e: DragEvent) => pickAss(e.dataTransfer?.files ?? null)

// ---------- 从已有角色库选择 ----------
const toggleHuman = (id: string) => {
  const index = selectedHumanIds.value.indexOf(id)
  index >= 0 ? selectedHumanIds.value.splice(index, 1) : selectedHumanIds.value.push(id)
}

// ---------- 提交 ----------
const submit = () => {
  if (!canSubmit.value || store.magicLoading) return
  store.runMagicScript({
    songId: songId.value.trim(),
    assFile: assFile.value!,
    digitalHumanIds: selectedHumanIds.value.length ? [...selectedHumanIds.value] : undefined,
    extraRequirement: extraRequirement.value.trim() || undefined,
    ratio: ratio.value,
    resolution: resolution.value,
    imageModel: imageModel.value,
    videoModel: videoModel.value,
  })
}

const cancel = () => {
  if (!store.magicLoading) store.closeMagic()
}
</script>

<template>
  <Teleport to="body">
    <div v-if="store.magicOpen" class="modal-mask" @click.self="cancel">
      <div class="modal">
        <header class="modal-header">
          <h3><AppIcon name="sparkles" :size="17" /> ASS 分镜</h3>
          <button class="close-btn" @click="cancel"><AppIcon name="close" :size="13" /> 关闭</button>
        </header>

        <div class="modal-body">
          <!-- 歌曲编号 -->
          <p class="field-label">歌曲编号 <span class="required">*</span></p>
          <input
            v-model="songId"
            class="song-input"
            placeholder="上传 ASS 文件后自动提取歌曲编号"
            disabled
          />
          <p class="song-id-hint">歌曲编号仅从 ASS 文件名提取，不支持手动修改。</p>

          <section class="generation-config">
            <p class="field-label">生成配置 <span class="required">*</span></p>
            <div class="config-grid">
              <label><span>画幅 *</span><select v-model="ratio"><option value="16:9">16:9</option><option value="9:16">9:16</option><option value="4:3">4:3</option><option value="1:1">1:1</option></select></label>
              <label><span>清晰度 *</span><select v-model="resolution"><option value="480p">480p</option><option value="720p">720p</option><option value="1080p">1080p</option></select></label>
              <label><span>视频模型 *</span><select v-model="videoModel" disabled><option v-for="item in VIDEO_MODEL_OPTIONS" :key="item.value" :value="item.value">{{ item.label }}</option></select></label>
              <label><span>图片模型 *</span><select v-model="imageModel" disabled><option v-for="item in IMAGE_MODEL_OPTIONS" :key="item.value" :value="item.value">{{ item.label }}</option></select></label>
            </div>
            <p class="model-hint">当前内测版模型固定，选项已保留用于后续扩展。</p>
          </section>

          <!-- 完整角色库横向多选 -->
          <div class="role-section">
            <p class="field-label">从已有角色库选择 <span class="optional">（可不选；选择后人物镜仅使用所选角色）</span></p>
            <div class="role-picker" :class="{ filled: selectedHumanIds.length }">
              <button
                v-for="human in store.digitalHumans"
                :key="human.id"
                class="role-card"
                :class="{ selected: selectedHumanIds.includes(human.id) }"
                :title="`${human.name} · ${human.style}`"
                @click="toggleHuman(human.id)"
              >
                <img :src="human.avatar" :alt="human.name" />
                <span>{{ human.name }}</span>
                <span v-if="selectedHumanIds.includes(human.id)" class="role-check">
                  <AppIcon name="check" :size="10" />
                </span>
              </button>
              <p v-if="!store.digitalHumans.length" class="role-empty">角色库暂无可选人物</p>
            </div>
          </div>

          <!-- 两栏：ass 文件 / 额外要求 -->
          <div class="upload-grid">
            <div class="upload-col">
              <p class="field-label">上传 ass 字幕文件 <span class="required">*</span></p>
              <div
                class="dropzone"
                :class="{ filled: assFile }"
                @click="assInputRef?.click()"
                @dragover.prevent
                @drop.prevent="onAssDrop"
              >
                <template v-if="assFile">
                  <span class="file-icon"><AppIcon name="file" :size="28" /></span>
                  <span class="file-name">{{ assFile.name }}</span>
                  <span class="file-tip">点击可重新选择</span>
                </template>
                <template v-else>
                  <span class="file-icon"><AppIcon name="file" :size="28" /></span>
                  <span class="drop-text">点击选择或拖入 .ass 文件</span>
                  <span class="file-tip">解析歌词与时间轴生成分镜</span>
                </template>
              </div>
              <input ref="assInputRef" type="file" accept=".ass" hidden @change="onAssChange" />
            </div>

            <div class="upload-col extra-col">
              <p class="field-label">额外要求 <span class="optional">（可空）</span></p>
              <textarea
                v-model="extraRequirement"
                class="extra-input"
                placeholder="如：整体氛围偏怀旧、多用空镜头、副歌处切快节奏…"
              />
            </div>
          </div>
          <p v-if="store.magicError" class="error-tip" role="alert">{{ store.magicError }}</p>
        </div>

        <footer class="modal-footer">
          <button
            class="btn-primary generate-btn"
            :disabled="!canSubmit || store.magicLoading"
            @click="submit"
          >
            <span v-if="store.magicLoading" class="spinner light" />
            <AppIcon v-else name="sparkles" :size="16" />
            {{ store.magicLoading ? '正在生成分镜…' : '生成' }}
          </button>
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
  width: 1040px;
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
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: var(--text);
}
.modal-header h3 .app-icon {
  color: var(--primary);
}
.close-btn {
  border: none;
  background: transparent;
  font-size: 14px;
  color: var(--text-secondary);
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.close-btn:hover {
  color: var(--text);
}
.modal-body {
  padding: 16px 22px;
  overflow-y: auto;
}
.field-label {
  margin: 0 0 8px;
  font-size: 13px;
  font-weight: 700;
  color: var(--text);
}
.required {
  color: var(--primary);
}
.optional {
  color: var(--text-secondary);
  font-weight: 400;
}

/* 歌曲编号 */
.song-input {
  width: 100%;
  border: 1px solid var(--border-dark);
  border-radius: 10px;
  padding: 10px 12px;
  font-size: 14px;
  outline: none;
  transition: border-color 0.15s;
}
.song-input:focus {
  border-color: var(--primary);
}
.song-input:disabled {
  background: #f5f5f6;
  color: var(--text-secondary);
  cursor: not-allowed;
}
.song-id-hint {
  margin: 6px 0 0;
  color: var(--text-secondary);
  font-size: 12px;
}
.generation-config{margin-top:16px}.config-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}.config-grid label{display:flex;flex-direction:column;gap:6px;font-size:12px;color:var(--text-secondary)}.config-grid select{width:100%;border:1px solid var(--border-dark);border-radius:9px;background:#fff;padding:9px 10px;color:var(--text)}.config-grid select:disabled{background:#f5f5f6;color:#777;cursor:not-allowed}.model-hint{margin:7px 0 0;color:var(--text-secondary);font-size:12px}@media(max-width:760px){.config-grid{grid-template-columns:1fr 1fr}}

/* ASS 文件与额外要求 */
.upload-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.2fr) minmax(0, 0.8fr);
  gap: 18px;
  margin-top: 16px;
}
@media (max-width: 640px) {
  .upload-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}
.upload-col {
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.dropzone {
  flex: 1;
  min-height: 170px;
  border: 1.5px dashed var(--border-dark);
  border-radius: 12px;
  background: #fafafa;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 12px;
  text-align: center;
  cursor: pointer;
  transition: border-color 0.15s, background 0.15s;
}
.dropzone:hover {
  border-color: var(--primary);
  background: var(--primary-light);
}
.dropzone.filled {
  border-style: solid;
  border-color: var(--primary);
  background: #fff;
}
.file-icon {
  display: inline-flex;
  color: var(--text-secondary);
}
.dropzone.filled .file-icon {
  color: var(--primary);
}
.drop-text {
  font-size: 13px;
  color: var(--text);
}
.file-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--text);
  word-break: break-all;
}
.file-tip {
  font-size: 12px;
  color: var(--text-secondary);
}

/* 已有角色库多选 */
.role-picker {
  min-height: 130px;
  overflow-x: auto;
  overflow-y: hidden;
  border: 1.5px dashed var(--border-dark);
  border-radius: 12px;
  background: #fafafa;
  padding: 10px;
  display: flex;
  flex-wrap: nowrap;
  gap: 10px;
  align-items: flex-start;
}
.role-section {
  margin-top: 16px;
}
.role-picker.filled {
  border-color: rgba(255, 90, 44, 0.45);
  background: #fff;
}
.role-card {
  position: relative;
  flex: 0 0 76px;
  width: 76px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: #fff;
  padding: 3px;
  color: var(--text-secondary);
  cursor: pointer;
  transition: border-color 0.15s, background 0.15s, transform 0.15s;
}
.role-card:hover {
  border-color: var(--primary);
  transform: translateY(-1px);
}
.role-card.selected {
  border-color: var(--primary);
  background: var(--primary-light);
  color: var(--primary);
}
.role-card img {
  width: 100%;
  height: 88px;
  object-fit: cover;
  border-radius: 6px;
  display: block;
}
.role-card > span:not(.role-check) {
  display: block;
  margin-top: 3px;
  font-size: 11px;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}
.role-check {
  position: absolute;
  top: 5px;
  right: 5px;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: var(--primary);
  color: #fff;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}
.role-empty {
  width: 100%;
  margin: auto 0;
  text-align: center;
  color: var(--text-secondary);
  font-size: 12px;
}

/* 额外要求 */
.extra-input {
  flex: 1;
  min-height: 170px;
  border: 1px solid var(--border-dark);
  border-radius: 12px;
  padding: 10px 12px;
  font-size: 13px;
  line-height: 1.6;
  font-family: inherit;
  resize: none;
  outline: none;
  transition: border-color 0.15s;
}
.extra-input:focus {
  border-color: var(--primary);
}

/* 底部生成按钮 */
.modal-footer {
  padding: 14px 22px 18px;
  border-top: 1px solid var(--border);
}
.generate-btn {
  width: 100%;
  justify-content: center;
  font-size: 15px;
  padding: 11px 0;
}
.error-tip {
  margin: 14px 0 0;
  padding: 10px 12px;
  border-radius: 8px;
  background: #fff0f0;
  color: #c33;
  font-size: 13px;
}
</style>
