<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import BaseModal from './base/BaseModal.vue'
import ImagePreviewCanvas from './ImagePreviewCanvas.vue'
import {
  closeImagePreview,
  selectPreviewImage,
  useImagePreview,
} from '../composables/useImagePreview'
import { downloadImage } from '../api/downloadImage'
const { state } = useImagePreview()
const downloading = ref(false),
  downloadError = ref('')
const thumbnailList = ref<HTMLElement>()
watch(
  () => state.index,
  () => {
    void nextTick(() =>
      thumbnailList.value
        ?.querySelector<HTMLElement>('[aria-pressed="true"]')
        ?.scrollIntoView?.({ block: 'nearest', inline: 'center' }),
    )
  },
)
const current = computed(() => state.items[state.index])
watch(
  () => state.src,
  () => {
    downloadError.value = ''
  },
)
const move = (delta: number) =>
  selectPreviewImage((state.index + delta + state.items.length) % state.items.length)
const onKey = (e: KeyboardEvent) => {
  if (e.key === 'ArrowLeft') {
    e.preventDefault()
    move(-1)
  }
  if (e.key === 'ArrowRight') {
    e.preventDefault()
    move(1)
  }
}
const download = async () => {
  if (downloading.value) return
  downloading.value = true
  downloadError.value = ''
  try {
    await downloadImage(state.src, state.alt)
  } catch {
    downloadError.value = '下载失败，请重试或打开原图保存'
  } finally {
    downloading.value = false
  }
}
</script>
<template>
  <BaseModal
    :open="state.open"
    :title="state.alt"
    aria-label="图片大图预览"
    level="nested"
    mask-variant="media"
    width="1200px"
    max-height="94vh"
    @close="closeImagePreview"
    @keydown="onKey"
  >
    <template #actions>
      <button class="preview-action" :disabled="downloading" @click="download">
        {{ downloading ? '下载中…' : '下载原图' }}
      </button>
    </template>
    <div class="gallery">
      <div v-if="downloadError" class="download-error" role="alert">
        {{ downloadError }} <a :href="state.src" target="_blank" rel="noopener">打开原图</a>
      </div>
      <ImagePreviewCanvas v-if="state.open" :src="state.src" :alt="state.alt" />
      <div v-if="state.items.length > 1" class="gallery-navigation">
        <button class="preview-action" aria-label="上一张" @click="move(-1)">‹</button>
        <div ref="thumbnailList" class="gallery-thumbnails" aria-label="预览图片列表">
          <button
            v-for="(item, index) in state.items"
            :key="`${item.src}-${index}`"
            class="gallery-thumbnail"
            :class="{ selected: index === state.index }"
            :aria-label="`查看${item.alt}`"
            :aria-pressed="index === state.index"
            @click="selectPreviewImage(index)"
          >
            <img :src="item.thumbnail || item.src" alt="" /><span>{{ item.alt }}</span>
          </button>
        </div>
        <button class="preview-action" aria-label="下一张" @click="move(1)">›</button>
      </div>
      <p class="gallery-caption">
        {{ state.index + 1 }} / {{ state.items.length }} · {{ current?.alt }}
      </p>
    </div>
  </BaseModal>
</template>
<style scoped>
.gallery {
  min-height: 0;
  overflow-y: auto;
}
.preview-action {
  border: 1px solid var(--preview-border);
  border-radius: var(--radius-sm);
  padding: 7px 12px;
  background: var(--preview-control);
  color: var(--preview-text);
  cursor: pointer;
}
.gallery-navigation {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 4px 16px;
}
.gallery-thumbnails {
  display: flex;
  flex: 1;
  gap: 8px;
  justify-content: flex-start;
  overflow-x: auto;
}
.gallery-thumbnail {
  width: 100px;
  flex: 0 0 auto;
  border: 2px solid transparent;
  border-radius: var(--radius-sm);
  padding: 3px;
  background: var(--preview-control);
  color: var(--preview-text);
  cursor: pointer;
}
.gallery-thumbnail:first-child {
  margin-left: auto;
}
.gallery-thumbnail:last-child {
  margin-right: auto;
}
.gallery-thumbnail.selected {
  border-color: var(--primary);
}
.gallery-thumbnail img {
  width: 100%;
  height: 45px;
  object-fit: contain;
}
.gallery-thumbnail span {
  display: block;
  font-size: var(--font-sm);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.gallery-caption {
  text-align: center;
  color: var(--preview-muted);
  font-size: var(--font-sm);
  margin: 8px;
}
.download-error {
  color: var(--preview-text);
  padding: 8px 16px;
}
.download-error a {
  color: var(--preview-text);
}
</style>
