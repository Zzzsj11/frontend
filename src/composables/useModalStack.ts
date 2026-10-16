import { reactive } from 'vue'

// 所有业务弹层共享栈，避免一次 Esc 关闭多层及丢失下层草稿。
const stack = reactive<symbol[]>([])
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
  const index = stack.indexOf(id)
  if (index < 0) return
  stack.splice(index, 1)
  if (!stack.length) document.body.style.overflow = previousOverflow
}
export const isTopModal = (id: symbol) => stack.at(-1) === id
export const isStackedModal = (id: symbol) => stack.indexOf(id) > 0
