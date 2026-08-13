<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useProjectStore } from '../stores/project'
import AppIcon from './AppIcon.vue'
import BaseModal from './base/BaseModal.vue'
import CharacterPortrait from './CharacterPortrait.vue'
import type { ShotGenOptions } from '../types'
import {
  DEFAULT_IMAGE_MODEL,
  DEFAULT_VIDEO_MODEL,
  IMAGE_MODEL_OPTIONS,
  VIDEO_MODEL_OPTIONS,
  loadGenerationModels,
} from '../generationModels'

const store = useProjectStore()

// 表单草稿
const songId = ref('')
const assFile = ref<File | null>(null)
const selectedHumanIds = ref<string[]>([])
const extraRequirement = ref('')
const ratio = ref<ShotGenOptions['ratio']>('16:9')
const resolution = ref<ShotGenOptions['resolution']>('480p')
const imageModel = ref(DEFAULT_IMAGE_MODEL)
const videoModel = ref(DEFAULT_VIDEO_MODEL)

const assInputRef = ref<HTMLInputElement>()

const canSubmit = computed(() => songId.value.trim() !== '' && assFile.value !== null)

const resetForm = () => {
  songId.value = ''
  assFile.value = null
  selectedHumanIds.value = [...store.castIds]
  extraRequirement.value = ''
  ratio.value = '16:9'
  resolution.value = '480p'
  imageModel.value = DEFAULT_IMAGE_MODEL
  videoModel.value = DEFAULT_VIDEO_MODEL
}

// 每次打开弹窗重置表单（immediate：弹层懒挂载后，挂载即打开，靠 immediate 完成初始化）
// 注意：必须声明在 resetForm 之后——immediate 回调在 watch() 调用处同步执行，提前引用 const 会触发 TDZ
watch(
  () => store.magicOpen,
  (open) => {
    if (open) {
      resetForm()
      void loadGenerationModels()
    }
  },
  { immediate: true },
)

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
  <BaseModal
    :open="store.magicOpen"
    width="1040px"
    :loading="store.magicLoading"
    aria-label="ASS 视频"
    @close="cancel"
  >
    <template #title><AppIcon name="sparkles" :size="17" /> ASS 视频</template>
    <div class="modal-body">
      <!-- 歌曲编号：单行弱化展示，上传 ASS 后自动提取 -->
      <div class="song-id-row">
        <span class="song-id-label">歌曲编号 <span class="required">*</span></span>
        <input
          v-model="songId"
          class="song-input"
          placeholder="上传 ASS 文件后自动提取歌曲编号"
          disabled
        />
        <span class="song-id-hint">仅从 ASS 文件名提取，不可手动修改</span>
      </div>

      <section class="generation-config">
        <p class="field-label">生成配置 <span class="required">*</span></p>
        <div class="config-grid">
          <label
            ><span>画幅 *</span
            ><select v-model="ratio">
              <option value="16:9">16:9</option>
              <option value="9:16">9:16</option>
              <option value="4:3">4:3</option>
              <option value="1:1">1:1</option>
            </select></label
          >
          <label
            ><span>清晰度 *</span
            ><select v-model="resolution">
              <option value="480p">480p</option>
              <option value="720p">720p</option>
              <option value="1080p">1080p</option>
            </select></label
          >
          <label
            ><span>视频模型 *</span
            ><select v-model="videoModel" disabled>
              <option v-for="item in VIDEO_MODEL_OPTIONS" :key="item.value" :value="item.value">
                {{ item.label }}
              </option>
            </select></label
          >
          <label
            ><span>图片模型 *</span
            ><select v-model="imageModel" disabled>
              <option v-for="item in IMAGE_MODEL_OPTIONS" :key="item.value" :value="item.value">
                {{ item.label }}
              </option>
            </select></label
          >
        </div>
        <p class="model-hint">当前内测版模型固定，选项已保留用于后续扩展。</p>
      </section>

      <!-- 完整角色库横向多选 -->
      <div class="role-section">
        <p class="field-label">
          从已有角色库选择 <span class="optional">（可不选；选择后人物镜仅使用所选角色）</span>
        </p>
        <div class="role-picker" :class="{ filled: selectedHumanIds.length }">
          <button
            v-for="human in store.digitalHumans"
            :key="human.id"
            class="role-card"
            :class="{ selected: selectedHumanIds.includes(human.id) }"
            :title="`${human.name} · ${human.style}`"
            @click="toggleHuman(human.id)"
          >
            <CharacterPortrait :src="human.avatar" :alt="human.name" />
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
              <span class="file-tip">解析歌词与时间轴生成视频脚本</span>
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

    <template #footer>
      <button
        class="btn-primary generate-btn"
        :disabled="!canSubmit || store.magicLoading"
        @click="submit"
      >
        <span v-if="store.magicLoading" class="spinner light" />
        <AppIcon v-else name="sparkles" :size="16" />
        {{ store.magicLoading ? '正在生成视频脚本…' : '生成' }}
      </button>
    </template>
  </BaseModal>
</template>

<style scoped>
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

/* 歌曲编号：单行弱化展示 */
.song-id-row {
  display: flex;
  align-items: center;
  gap: 10px;
}
.song-id-label {
  flex: none;
  color: var(--text-secondary);
  font-size: var(--font-sm);
  white-space: nowrap;
}
.song-input {
  flex: 1;
  min-width: 0;
  border: 1px solid var(--border-dark);
  border-radius: var(--radius-sm);
  padding: 6px 10px;
  font-size: var(--font-sm);
  outline: none;
  transition: border-color 0.15s;
}
.song-input:focus {
  border-color: var(--primary);
}
.song-input:disabled {
  background: var(--surface-muted);
  color: var(--text-secondary);
  cursor: not-allowed;
}
.song-id-hint {
  flex: none;
  color: var(--text-secondary);
  font-size: var(--font-sm);
  white-space: nowrap;
}
.generation-config {
  margin-top: 16px;
}
.config-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}
.config-grid label {
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: var(--font-sm);
  color: var(--text-secondary);
}
.config-grid select {
  width: 100%;
  border: 1px solid var(--border-dark);
  border-radius: var(--radius-sm);
  background: #fff;
  padding: 9px 10px;
  color: var(--text);
}
.config-grid select:disabled {
  background: var(--surface-muted);
  color: var(--text-secondary);
  cursor: not-allowed;
}
.model-hint {
  margin: 7px 0 0;
  color: var(--text-secondary);
  font-size: var(--font-sm);
}
@media (max-width: 760px) {
  .config-grid {
    grid-template-columns: 1fr 1fr;
  }
}

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
  border-radius: var(--radius-md);
  background: var(--surface-muted);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 12px;
  text-align: center;
  cursor: pointer;
  transition:
    border-color 0.15s,
    background 0.15s;
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
  font-size: var(--font-sm);
  color: var(--text-secondary);
}

/* 已有角色库多选 */
.role-picker {
  min-height: 120px;
  max-height: 250px;
  overflow-x: hidden;
  overflow-y: auto;
  border: 1.5px dashed var(--border-dark);
  border-radius: var(--radius-md);
  background: var(--surface-muted);
  padding: 10px;
  display: flex;
  flex-wrap: wrap;
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
  flex: 1 1 124px;
  width: 124px;
  max-width: 160px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: #fff;
  padding: 3px;
  color: var(--text-secondary);
  cursor: pointer;
  transition:
    border-color 0.15s,
    background 0.15s,
    transform 0.15s;
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
  height: 70px;
  object-fit: contain;
  border-radius: var(--radius-sm);
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
  font-size: var(--font-sm);
}

/* 额外要求 */
.extra-input {
  flex: 1;
  min-height: 170px;
  border: 1px solid var(--border-dark);
  border-radius: var(--radius-md);
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
.generate-btn {
  width: 100%;
  justify-content: center;
  font-size: 15px;
  padding: 11px 0;
}
.error-tip {
  margin: 14px 0 0;
  padding: 10px 12px;
  border-radius: var(--radius-sm);
  background: var(--danger-light);
  color: var(--danger);
  font-size: 13px;
}
.role-card .character-portrait {
  width: 100%;
  height: 70px;
  border-radius: var(--radius-sm);
}
</style>
