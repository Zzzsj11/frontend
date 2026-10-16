import { reactive } from 'vue'

export interface PreviewImage {
  src: string
  alt: string
  thumbnail?: string
}
const state = reactive({
  open: false,
  src: '',
  alt: '原图预览',
  items: [] as PreviewImage[],
  index: 0,
})
export function selectPreviewImage(index: number) {
  const item = state.items[index]
  if (!item) return
  state.index = index
  state.src = item.src
  state.alt = item.alt
}
export function openImageGallery(items: PreviewImage[], index = 0) {
  const selected = items[index]
  state.items = items.filter((item) => Boolean(item.src))
  if (!state.items.length) return
  selectPreviewImage(Math.max(0, state.items.indexOf(selected!)))
  state.open = true
}
export function openImagePreview(src?: string, alt = '原图预览') {
  if (src) openImageGallery([{ src, alt }])
}
export function closeImagePreview() {
  state.open = false
}
export function useImagePreview() {
  return { state, close: closeImagePreview }
}
