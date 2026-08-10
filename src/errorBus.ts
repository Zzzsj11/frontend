import { reactive } from 'vue'

export interface AppErrorNotice { id: number; title: string; message: string; errorCode?: string; status?: number }
const state = reactive({ queue: [] as AppErrorNotice[], nextId: 1 })

export const errorBus = {
  state,
  show(input: Omit<AppErrorNotice, 'id'>) {
    if (!state.queue.some((item) => item.message === input.message && item.errorCode === input.errorCode)) state.queue.push({ id: state.nextId++, ...input })
  },
  dismiss(id: number) { state.queue = state.queue.filter((item) => item.id !== id) },
}

export class ApiError extends Error {
  status?: number
  errorCode?: string
  constructor(message: string, status?: number, errorCode?: string) { super(message); this.name = 'ApiError'; this.status = status; this.errorCode = errorCode }
}

export function reportApiError(error: unknown, fallback = '请求失败'): ApiError {
  const localMessage = error instanceof Error ? error.message : ''
  const isBrowserNetworkError = error instanceof TypeError && /failed to fetch|networkerror|load failed/i.test(localMessage)
  const isBrowserTimeout = error instanceof DOMException && error.name === 'AbortError'
  const value = error instanceof ApiError ? error : new ApiError(isBrowserTimeout ? '请求超时，请稍后重试' : isBrowserNetworkError ? fallback : localMessage || fallback)
  errorBus.show({ title: value.status && value.status >= 500 ? '服务异常' : '操作未完成', message: value.message, errorCode: value.errorCode, status: value.status })
  return value
}
