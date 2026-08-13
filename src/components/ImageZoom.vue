<script setup lang="ts">
import AppIcon from './AppIcon.vue'
import { openImagePreview } from '../composables/useImagePreview'

/**
 * 图片「查看大图」触发按钮（P3b 单例化后不再自持弹层）。
 * 点击写入全局预览状态，遮罩由 ImagePreviewOverlay（Root.vue 挂载一次）统一渲染。
 *
 * 交互约定：hover 仅显示右下角「查看大图」按钮（由 CSS 控制），点击按钮才打开大图，
 * 避免全屏预览浮层遮挡上层弹窗（如数字人详情）。
 */
const props = withDefaults(defineProps<{ src?: string; alt?: string; label?: string }>(), {
  src: undefined,
  alt: '原图预览',
  label: '查看大图',
})

const show = () => openImagePreview(props.src, props.alt)
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
  bottom: 5px;
  z-index: 5;
  display: grid;
  width: 26px;
  height: 26px;
  place-items: center;
  padding: 0;
  border: 1px solid rgba(255, 255, 255, 0.68);
  border-radius: var(--radius-sm);
  background: rgba(25, 25, 28, 0.68);
  color: #fff;
  box-shadow: 0 3px 12px rgba(0, 0, 0, 0.2);
  cursor: pointer;
  opacity: 0;
  transform: translateY(3px) scale(0.94);
  transition:
    opacity 0.15s,
    transform 0.15s,
    background 0.15s,
    box-shadow 0.15s;
}
.image-zoom-trigger:hover,
.image-zoom-trigger:focus-visible {
  background: var(--primary, var(--primary));
  box-shadow: 0 5px 16px rgba(255, 90, 44, 0.4);
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
