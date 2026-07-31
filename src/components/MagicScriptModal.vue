<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useProjectStore } from '../stores/project'
import AppIcon from './AppIcon.vue'

const store = useProjectStore()

// 表单草稿
const songId = ref('')
const assFile = ref<File | null>(null)
const characterImages = ref<File[]>([])
const previewUrls = ref<string[]>([])
const extraRequirement = ref('')

const assInputRef = ref<HTMLInputElement>()
const imgInputRef = ref<HTMLInputElement>()

const canSubmit = computed(() => songId.value.trim() !== '' && assFile.value !== null)

// 每次打开弹窗重置表单
watch(
  () => store.magicOpen,
  (open) => {
    if (open) resetForm()
  },
)

const revokeAll = () => {
  previewUrls.value.forEach((u) => URL.revokeObjectURL(u))
  previewUrls.value = []
}

const resetForm = () => {
  songId.value = ''
  assFile.value = null
  characterImages.value = []
  extraRequirement.value = ''
  revokeAll()
}

onBeforeUnmount(revokeAll)

// ---------- ass 文件 ----------
const pickAss = (files: FileList | null) => {
  const file = files?.[0]
  if (!file) return
  assFile.value = file
}
const onAssChange = (e: Event) => {
  pickAss((e.target as HTMLInputElement).files)
  ;(e.target as HTMLInputElement).value = ''
}
const onAssDrop = (e: DragEvent) => pickAss(e.dataTransfer?.files ?? null)

// ---------- 人物图 ----------
const addImages = (files: FileList | null) => {
  if (!files) return
  for (const file of Array.from(files)) {
    if (!file.type.startsWith('image/')) continue
    characterImages.value.push(file)
    previewUrls.value.push(URL.createObjectURL(file))
  }
}
const onImgChange = (e: Event) => {
  addImages((e.target as HTMLInputElement).files)
  ;(e.target as HTMLInputElement).value = ''
}
const onImgDrop = (e: DragEvent) => addImages(e.dataTransfer?.files ?? null)
const removeImage = (index: number) => {
  characterImages.value.splice(index, 1)
  URL.revokeObjectURL(previewUrls.value[index])
  previewUrls.value.splice(index, 1)
}

// ---------- 提交 ----------
const submit = () => {
  if (!canSubmit.value || store.magicLoading) return
  store.runMagicScript({
    songId: songId.value.trim(),
    assFile: assFile.value!,
    characterImages: characterImages.value.length ? [...characterImages.value] : undefined,
    extraRequirement: extraRequirement.value.trim() || undefined,
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
          <h3><AppIcon name="sparkles" :size="17" /> MV 分镜</h3>
          <button class="close-btn" @click="cancel"><AppIcon name="close" :size="13" /> 关闭</button>
        </header>

        <div class="modal-body">
          <!-- 歌曲编号 -->
          <p class="field-label">歌曲编号 <span class="required">*</span></p>
          <input
            v-model="songId"
            class="song-input"
            placeholder="输入歌曲编号，如 SM-2026-0731"
          />

          <!-- 三栏：ass 文件 / 人物图 / 额外要求 -->
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

            <div class="upload-col">
              <p class="field-label">上传人物图 <span class="optional">（可空）</span></p>
              <div
                class="dropzone"
                :class="{ filled: characterImages.length }"
                @click="imgInputRef?.click()"
                @dragover.prevent
                @drop.prevent="onImgDrop"
              >
                <template v-if="characterImages.length">
                  <div class="img-list" @click.stop>
                    <div v-for="(url, i) in previewUrls" :key="url" class="img-thumb">
                      <img :src="url" alt="" />
                      <button class="img-remove" title="移除" @click="removeImage(i)">
                        <AppIcon name="close" :size="10" />
                      </button>
                    </div>
                    <button class="img-add" title="继续添加" @click="imgInputRef?.click()">
                      <AppIcon name="plus" :size="18" />
                    </button>
                  </div>
                </template>
                <template v-else>
                  <span class="file-icon"><AppIcon name="user" :size="28" /></span>
                  <span class="drop-text">点击选择或拖入人物参考图</span>
                  <span class="file-tip">用于统一 MV 角色形象，可多张</span>
                </template>
              </div>
              <input
                ref="imgInputRef"
                type="file"
                accept="image/*"
                multiple
                hidden
                @change="onImgChange"
              />
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
  width: 760px;
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

/* 三栏上传区 */
.upload-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr) minmax(0, 0.75fr);
  gap: 14px;
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

/* 人物图预览 */
.img-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: center;
  cursor: default;
}
.img-thumb {
  position: relative;
  width: 64px;
  height: 64px;
  border-radius: 8px;
  overflow: hidden;
  border: 1px solid var(--border);
}
.img-thumb img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}
.img-remove {
  position: absolute;
  top: 2px;
  right: 2px;
  width: 18px;
  height: 18px;
  border: none;
  border-radius: 50%;
  background: rgba(0, 0, 0, 0.55);
  color: #fff;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
}
.img-add {
  width: 64px;
  height: 64px;
  border: 1.5px dashed var(--border-dark);
  border-radius: 8px;
  background: transparent;
  color: var(--text-secondary);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: border-color 0.15s, color 0.15s;
}
.img-add:hover {
  border-color: var(--primary);
  color: var(--primary);
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
</style>
