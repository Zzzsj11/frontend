import { reactive } from 'vue'

/**
 * 全局单例图片预览（P3b：ImageZoom 去实例化）。
 *
 * 改造前：每处图片缩略图挂载一个 ImageZoom 组件实例 + 一个 Teleport + 一个全局
 * keydown 监听，百行分镜列表即上百个常驻监听器。
 * 改造后：ImageZoom 只保留触发按钮，点击写入本模块状态；唯一的遮罩层由
 * ImagePreviewOverlay（Root.vue 挂载一次）渲染，监听器 O(1)。
 */
const state = reactive({
  open: false,
  src: '',
  alt: '原图预览',
})

export function openImagePreview(src?: string, alt = '原图预览') {
  if (!src) return
  state.src = src
  state.alt = alt
  state.open = true
  document.body.style.overflow = 'hidden'
}

export function closeImagePreview() {
  if (!state.open) return
  state.open = false
  document.body.style.overflow = ''
}

export function useImagePreview() {
  return { state, close: closeImagePreview }
}
