<script setup lang="ts">
import { ref, watch } from 'vue'
import { useImageViewport } from '../composables/useImageViewport'
const props = defineProps<{ src: string; alt: string }>()
const failed = ref(false),
  loading = ref(true),
  attempt = ref(0)
const { viewport, scale, style, fit, zoom, loaded, pointerDown, pointerMove, pointerUp, wheel } =
  useImageViewport()
watch(
  () => props.src,
  () => {
    failed.value = false
    loading.value = true
  },
)
const bindViewport = (element: unknown) => {
  viewport.value = element as HTMLElement
}
const onLoad = (e: Event) => {
  loaded(e.target as HTMLImageElement)
  loading.value = false
}
const onError = () => {
  failed.value = true
  loading.value = false
}
const retry = () => {
  failed.value = false
  loading.value = true
  attempt.value++
}
</script>
<template>
  <div class="image-canvas-shell">
    <div
      :ref="bindViewport"
      class="image-viewport"
      aria-label="图片缩放区域"
      @wheel.prevent="wheel"
      @pointerdown="pointerDown"
      @pointermove="pointerMove"
      @pointerup="pointerUp"
      @pointercancel="pointerUp"
      @lostpointercapture="pointerUp"
    >
      <img
        v-if="!failed"
        :key="`${src}-${attempt}`"
        :src="src"
        :alt="alt"
        :style="style"
        :class="{ loading }"
        draggable="false"
        @load="onLoad"
        @error="onError"
      />
      <span v-if="loading" class="load-state" role="status">正在加载原图…</span>
      <div v-if="failed" class="load-state" role="alert">
        <p>原图加载失败</p>
        <button @pointerdown.stop @click="retry">重新加载</button>
      </div>
    </div>
    <div class="image-tools" aria-label="图片缩放工具">
      <button :disabled="loading || failed" aria-label="缩小" @click="zoom(scale / 1.25)">−</button>
      <output aria-label="缩放比例">{{ Math.round(scale * 100) }}%</output>
      <button :disabled="loading || failed" aria-label="放大" @click="zoom(scale * 1.25)">
        ＋
      </button>
      <button :disabled="loading || failed" @click="zoom(1)">原始尺寸</button>
      <button :disabled="loading || failed" @click="fit">适应窗口</button>
      <span class="gesture-hint">滚轮 / 双指缩放，拖动查看</span>
    </div>
  </div>
</template>
<style scoped>
.image-canvas-shell {
  min-height: 0;
  display: flex;
  flex-direction: column;
}
.image-viewport {
  height: min(62vh, 740px);
  min-height: 180px;
  overflow: hidden;
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  touch-action: none;
  cursor: grab;
}
.image-viewport:active {
  cursor: grabbing;
}
.image-viewport img {
  flex: none;
  max-width: none;
  max-height: none;
  object-fit: contain;
  user-select: none;
}
.image-viewport img.loading {
  opacity: 0;
}
.load-state {
  position: absolute;
  text-align: center;
  color: var(--preview-text);
}
.image-tools {
  display: flex;
  align-items: center;
  justify-content: center;
  flex-wrap: wrap;
  gap: 8px;
  padding: 10px;
  color: var(--preview-text);
}
button {
  border: 1px solid var(--preview-border);
  border-radius: var(--radius-sm);
  background: var(--preview-control);
  color: var(--preview-text);
  padding: 7px 12px;
  cursor: pointer;
}
button:disabled {
  opacity: 0.5;
  cursor: default;
}
output {
  min-width: 52px;
  text-align: center;
}
.gesture-hint {
  font-size: var(--font-sm);
  color: var(--preview-muted);
}
@media (max-width: 600px) {
  .gesture-hint {
    display: none;
  }
  .image-viewport {
    height: 52vh;
  }
}
</style>
