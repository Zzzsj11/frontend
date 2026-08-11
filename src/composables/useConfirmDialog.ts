import { reactive } from 'vue'

export interface ConfirmDialogOptions {
  title?: string
  message: string
  confirmText?: string
  cancelText?: string
  danger?: boolean
}

const state = reactive({
  open: false,
  title: '操作确认',
  message: '',
  confirmText: '确定',
  cancelText: '取消',
  danger: false,
})

let resolver: ((confirmed: boolean) => void) | null = null

export function confirmDialog(options: ConfirmDialogOptions | string): Promise<boolean> {
  if (resolver) resolver(false)
  const config = typeof options === 'string' ? { message: options } : options
  Object.assign(state, {
    open: true,
    title: config.title ?? '操作确认',
    message: config.message,
    confirmText: config.confirmText ?? '确定',
    cancelText: config.cancelText ?? '取消',
    danger: config.danger ?? false,
  })
  return new Promise<boolean>((resolve) => {
    resolver = resolve
  })
}

export function closeConfirmDialog(confirmed: boolean) {
  if (!state.open) return
  state.open = false
  const resolve = resolver
  resolver = null
  resolve?.(confirmed)
}

export function useConfirmDialog() {
  return { state, close: closeConfirmDialog }
}
