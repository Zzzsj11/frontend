import { computed, reactive, shallowReactive } from 'vue'

// 所有业务弹层共享栈，避免一次 Esc 关闭多层及丢失下层草稿。
const stack = reactive<symbol[]>([])
const panels = shallowReactive(new Map<symbol, HTMLElement>())

export const topModalPanel = computed(() => {
  const top = stack.at(-1)
  return top ? panels.get(top) : undefined
})

export function setModalPanel(id: symbol, panel?: HTMLElement) {
  if (panel) panels.set(id, panel)
  else panels.delete(id)
}
let previousOverflow = ''
export function registerModal(id: symbol) {
  if (stack.includes(id)) return
  if (!stack.length) {
    previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
  }
  stack.push(id)
}
export function unregisterModal(id: symbol) {
  panels.delete(id)
  const index = stack.indexOf(id)
  if (index < 0) return
  stack.splice(index, 1)
  if (!stack.length) document.body.style.overflow = previousOverflow
}
export const isTopModal = (id: symbol) => stack.at(-1) === id
export const isStackedModal = (id: symbol) => stack.indexOf(id) > 0
