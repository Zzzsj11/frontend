<script setup lang="ts">
import { onBeforeUnmount, watch } from 'vue'
import AppIcon from './AppIcon.vue'
import { closeImagePreview, useImagePreview } from '../composables/useImagePreview'

/** 全局唯一的图片预览遮罩（P3b）：全应用挂载一次（Root.vue），替代原每行一个的 ImageZoom 弹层 */
const { state } = useImagePreview()

const onKeydown = (event: KeyboardEvent) => {
  if (event.key === 'Escape') closeImagePreview()
}
watch(
  () => state.open,
  (open) => {
    if (open) window.addEventListener('keydown', onKeydown)
    else window.removeEventListener('keydown', onKeydown)
  },
)
onBeforeUnmount(() => window.removeEventListener('keydown', onKeydown))
</script>

<template>
  <Teleport to="body">
    <div
      v-if="state.open"
      class="image-zoom-mask"
      role="dialog"
      aria-modal="true"
      :aria-label="state.alt"
      @click.self="closeImagePreview"
    >
      <div class="image-zoom-dialog">
        <button
          class="image-zoom-close"
          type="button"
          title="关闭大图"
          aria-label="关闭大图"
          @click="closeImagePreview"
        >
          <AppIcon name="close" :size="18" />
        </button>
        <img :src="state.src" :alt="state.alt" />
        <span>{{ state.alt }}</span>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.image-zoom-mask {
  position: fixed;
  inset: 0;
  z-index: 2000;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 28px;
  background: rgba(12, 12, 15, 0.82);
  backdrop-filter: blur(4px);
}
.image-zoom-dialog {
  position: relative;
  display: flex;
  max-width: min(1200px, 92vw);
  max-height: 92vh;
  flex-direction: column;
  gap: 8px;
  padding: 12px;
  border: 1px solid rgba(255, 255, 255, 0.28);
  border-radius: var(--radius-lg);
  background: #19191c;
  box-shadow: 0 28px 90px rgba(0, 0, 0, 0.55);
}
.image-zoom-dialog img {
  display: block;
  max-width: 100%;
  max-height: calc(92vh - 58px);
  object-fit: contain;
  border-radius: var(--radius-sm);
  background: var(--border);
}
.image-zoom-dialog span {
  color: #fff;
  text-align: center;
  font-size: var(--font-sm);
}
.image-zoom-close {
  position: absolute;
  top: 18px;
  right: 18px;
  z-index: 1;
  display: grid;
  width: 34px;
  height: 34px;
  flex: 0 0 auto;
  place-items: center;
  border: 1px solid rgba(255, 255, 255, 0.5);
  border-radius: 50%;
  background: rgba(0, 0, 0, 0.62);
  color: #fff;
  cursor: pointer;
  transition:
    background 0.15s,
    transform 0.15s;
}
.image-zoom-close:hover {
  background: var(--primary, var(--primary));
  transform: scale(1.08);
}
</style>
