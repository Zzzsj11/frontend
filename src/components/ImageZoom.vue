<script setup lang="ts">
import { onBeforeUnmount, ref } from 'vue'
import AppIcon from './AppIcon.vue'

const props = withDefaults(defineProps<{ src?: string; alt?: string; label?: string }>(), {
  src: undefined,
  alt: '原图预览',
  label: '查看大图',
})

const open = ref(false)

// 交互约定：hover 仅显示右下角「查看大图」按钮（由 CSS 控制），点击按钮才打开大图，
// 避免全屏预览浮层遮挡上层弹窗（如数字人详情）。
const show = () => {
  if (!props.src) return
  open.value = true
  document.body.style.overflow = 'hidden'
}

const close = () => {
  open.value = false
  document.body.style.overflow = ''
}

const onKeydown = (event: KeyboardEvent) => {
  if (event.key === 'Escape' && open.value) close()
}

if (typeof window !== 'undefined') window.addEventListener('keydown', onKeydown)
onBeforeUnmount(() => {
  if (typeof window !== 'undefined') window.removeEventListener('keydown', onKeydown)
  if (open.value) document.body.style.overflow = ''
})
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
  <Teleport to="body">
    <div
      v-if="open"
      class="image-zoom-mask"
      role="dialog"
      aria-modal="true"
      :aria-label="label"
      @click.self="close"
    >
      <div class="image-zoom-dialog">
        <button
          class="image-zoom-close"
          type="button"
          title="关闭大图"
          aria-label="关闭大图"
          @click="close"
        >
          <AppIcon name="close" :size="18" />
        </button>
        <img :src="src" :alt="alt" />
        <span>{{ alt }}</span>
      </div>
    </div>
  </Teleport>
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
@media (hover: none) {
  .image-zoom-trigger {
    opacity: 1;
    transform: none;
  }
}
</style>
