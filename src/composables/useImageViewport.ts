import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

export function useImageViewport() {
  const viewport = ref<HTMLElement>()
  const width = ref(0),
    height = ref(0),
    scale = ref(1),
    x = ref(0),
    y = ref(0)
  const bounds = ref({ width: 1, height: 1 })
  const pointers = new Map<number, { x: number; y: number }>()
  let observer: ResizeObserver | undefined
  const fitScale = computed(() =>
    Math.min(
      1,
      (bounds.value.width - 24) / (width.value || 1),
      (bounds.value.height - 24) / (height.value || 1),
    ),
  )
  const clamp = () => {
    const maxX = Math.max(0, (width.value * scale.value - bounds.value.width) / 2)
    const maxY = Math.max(0, (height.value * scale.value - bounds.value.height) / 2)
    x.value = Math.max(-maxX, Math.min(maxX, x.value))
    y.value = Math.max(-maxY, Math.min(maxY, y.value))
  }
  const fit = () => {
    scale.value = Math.max(0.01, fitScale.value)
    x.value = 0
    y.value = 0
  }
  const zoom = (value: number) => {
    scale.value = Math.max(Math.min(fitScale.value, 0.1), Math.min(5, value))
    clamp()
  }
  const loaded = (image: HTMLImageElement) => {
    width.value = image.naturalWidth
    height.value = image.naturalHeight
    fit()
  }
  const distance = () => {
    const [a, b] = [...pointers.values()]
    return a && b ? Math.hypot(a.x - b.x, a.y - b.y) : 0
  }
  const pointerDown = (e: PointerEvent) => {
    if (e.pointerType === 'mouse' && e.button !== 0) return
    pointers.set(e.pointerId, { x: e.clientX, y: e.clientY })
    viewport.value?.setPointerCapture(e.pointerId)
  }
  const pointerMove = (e: PointerEvent) => {
    const old = pointers.get(e.pointerId)
    if (!old) return
    const before = distance()
    pointers.set(e.pointerId, { x: e.clientX, y: e.clientY })
    if (pointers.size > 1 && before > 0) zoom((scale.value * distance()) / before)
    else {
      x.value += e.clientX - old.x
      y.value += e.clientY - old.y
      clamp()
    }
  }
  const pointerUp = (e: PointerEvent) => pointers.delete(e.pointerId)
  const wheel = (e: WheelEvent) => zoom(scale.value * (e.deltaY < 0 ? 1.15 : 1 / 1.15))
  const style = computed(() => ({
    width: `${width.value}px`,
    height: `${height.value}px`,
    transform: `translate(${x.value}px, ${y.value}px) scale(${scale.value})`,
  }))
  onMounted(() => {
    if (!viewport.value) return
    if (typeof ResizeObserver === 'undefined') {
      bounds.value = viewport.value.getBoundingClientRect()
      fit()
      return
    }
    observer = new ResizeObserver(([entry]) => {
      if (!entry) return
      bounds.value = { width: entry.contentRect.width, height: entry.contentRect.height }
      fit()
    })
    observer.observe(viewport.value)
  })
  onBeforeUnmount(() => observer?.disconnect())
  return { viewport, scale, style, fit, zoom, loaded, pointerDown, pointerMove, pointerUp, wheel }
}
