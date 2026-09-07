import { reactive } from 'vue'

export interface AppErrorNotice {
  id: number
  title: string
  message: string
  errorCode?: string
  status?: number
  repeatCount?: number
}
const state = reactive({ queue: [] as AppErrorNotice[], nextId: 1 })

export const errorBus = {
  state,
  show(input: Omit<AppErrorNotice, 'id'>) {
    // 同类错误合并展示，但保留发生次数，避免批量任务看起来只失败了一条。
    const duplicate = state.queue.find(
      (item) => item.message === input.message && item.errorCode === input.errorCode,
    )
    if (duplicate) {
      duplicate.repeatCount = (duplicate.repeatCount ?? 1) + (input.repeatCount ?? 1)
      return
    }
    state.queue.push({ id: state.nextId++, repeatCount: 1, ...input })
  },
  dismiss(id: number) {
    state.queue = state.queue.filter((item) => item.id !== id)
  },
  dismissAll() {
    state.queue = []
  },
}

export type ErrorCategory =
  'content_safety' | 'provider_submission' | 'balance' | 'network' | 'other'

export function classifyErrorMessage(message: string): { category: ErrorCategory; label: string } {
  if (/敏感|安全合规|content policy|sensitive (?:content|information)|unsafe/i.test(message))
    return { category: 'content_safety', label: '内容安全校验' }
  if (/供应商创建|幂等|manual.review|无法确认结果/i.test(message))
    return { category: 'provider_submission', label: '供应商创建状态不确定' }
  if (/余额|额度|充值/i.test(message)) return { category: 'balance', label: '余额或额度' }
  if (/网络|连接|timeout|timed out|超时/i.test(message))
    return { category: 'network', label: '网络或超时' }
  return { category: 'other', label: '其他错误' }
}

export class ApiError extends Error {
  status?: number
  errorCode?: string
  constructor(message: string, status?: number, errorCode?: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.errorCode = errorCode
  }
}

export function reportApiError(error: unknown, fallback = '请求失败'): ApiError {
  const localMessage = error instanceof Error ? error.message : ''
  const isBrowserNetworkError =
    error instanceof TypeError && /failed to fetch|networkerror|load failed/i.test(localMessage)
  const isBrowserTimeout = error instanceof DOMException && error.name === 'AbortError'
  const value =
    error instanceof ApiError
      ? error
      : new ApiError(
          isBrowserTimeout
            ? '请求超时，请稍后重试'
            : isBrowserNetworkError
              ? fallback
              : localMessage || fallback,
        )
  errorBus.show({
    title: value.status && value.status >= 500 ? '服务异常' : '操作未完成',
    message: value.message,
    errorCode: value.errorCode,
    status: value.status,
  })
  return value
}
