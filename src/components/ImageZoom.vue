<script setup lang="ts">
import AppIcon from './AppIcon.vue'
import {
  openImageGallery,
  openImagePreview,
  type PreviewImage,
} from '../composables/useImagePreview'

/**
 * 图片「查看大图」触发按钮（P3b 单例化后不再自持弹层）。
 * 点击写入全局预览状态，遮罩由 ImagePreviewOverlay（Root.vue 挂载一次）统一渲染。
 *
 * 交互约定：hover 仅显示右下角「查看大图」按钮（由 CSS 控制），点击按钮才打开大图，
 * 避免全屏预览浮层遮挡上层弹窗（如数字人详情）。
 */
const props = withDefaults(
  defineProps<{
    src?: string
    alt?: string
    label?: string
    items?: PreviewImage[]
    index?: number
  }>(),
  {
    src: undefined,
    alt: '原图预览',
    label: '查看大图',
    items: undefined,
    index: 0,
  },
)

const show = () =>
  props.items ? openImageGallery(props.items, props.index) : openImagePreview(props.src, props.alt)
</script>

<template>
  <button
    v-if="src"
    class="image-zoom-trigger"
    type="button"
    :title="label"
    :aria-label="label"
    @click.stop="show"
  >
    <AppIcon name="zoom-in" :size="17" />
  </button>
</template>

<style scoped>
.image-zoom-trigger {
  position: absolute;
  right: 5px;
  top: 5px;
  z-index: var(--z-local-controls);
  display: grid;
  width: 26px;
  height: 26px;
  place-items: center;
  padding: 0;
  border: 1px solid var(--preview-border);
  border-radius: var(--radius-sm);
  background: var(--preview-control);
  color: var(--preview-text);
  box-shadow: var(--shadow-card);
  cursor: pointer;
  opacity: 1;
  transition:
    opacity 0.15s,
    transform 0.15s,
    background 0.15s,
    box-shadow 0.15s;
}
.image-zoom-trigger:hover,
.image-zoom-trigger:focus-visible {
  background: var(--primary, var(--primary));
  box-shadow: var(--shadow-card);
  outline: none;
  transform: translateY(0) scale(1.08);
}
:global(*:hover) > .image-zoom-trigger,
.image-zoom-trigger:focus-visible {
  opacity: 1;
  transform: translateY(0) scale(1);
}
@media (hover: none) {
  .image-zoom-trigger {
    opacity: 1;
    transform: none;
  }
}
</style>
