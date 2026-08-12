import { ApiError, reportApiError } from '../errorBus'
import { isPollingHeaders, recordApiTiming } from '../perf'

let accessToken = ''
let refreshPromise: Promise<boolean> | null = null
/** 用户主动退出登录后置位：在途请求/轮询撞上 401 时静默失败，不再弹“登录已过期”或强制跳转 */
let intentionalLogout = false
const NETWORK_RETRY_DELAYS_MS = [500, 1500]
// 502/503 是 nginx 在上游不可达时直接返回的（部署重启窗口），请求从未到达后端，
// 因此任何方法（含 POST）都可安全重放；预算覆盖一次平滑切换的收敛时间
const GATEWAY_RETRY_DELAYS_MS = [1000, 2000, 4000, 8000]
const wait = (delayMs: number) => new Promise((resolve) => setTimeout(resolve, delayMs))
export const setAccessToken = (value: string) => {
  accessToken = value
}
/** 重置会话辅助状态（测试清理 / 登录页兜底）：清 token、退出标志与进行中的刷新 */
export function resetAuthState() {
  accessToken = ''
  intentionalLogout = false
  refreshPromise = null
}
const refreshAccess = async () => {
  if (!refreshPromise)
    refreshPromise = fetch('/api/auth/refresh', { method: 'POST', credentials: 'include' })
      .then(async (response) => {
        if (!response.ok) return false
        setAccessToken(((await response.json()) as { accessToken: string }).accessToken)
        return true
      })
      .finally(() => {
        refreshPromise = null
      })
  return refreshPromise
}
/** token 彻底失效时清空本地状态并跳转登录页 */
const forceLogout = () => {
  accessToken = ''
  // 避免循环 redirect：当前已在 /login 页则不再跳转
  if (window.location.pathname !== '/login') {
    window.location.href = `/login?redirect=${encodeURIComponent(window.location.pathname + window.location.search)}`
  }
}
export async function apiRequest<T>(
  path: string,
  init: RequestInit = {},
  retry = true,
): Promise<T> {
  const headers = new Headers(init.headers)
  if (accessToken) headers.set('Authorization', `Bearer ${accessToken}`)
  if (init.body && !(init.body instanceof FormData) && !headers.has('Content-Type'))
    headers.set('Content-Type', 'application/json')
  // 轮询/长连接请求不进入性能埋点（与后端全量日志同一语义）
  const tracked = !isPollingHeaders(headers)
  const t0 = tracked ? performance.now() : 0
  let response: Response | undefined
  let retried = false
  const request = () => fetch(`/api${path}`, { ...init, headers, credentials: 'include' })
  try {
    response = await request()
  } catch (error) {
    // Generation jobs are polled for several minutes. A single transient proxy or
    // network interruption must not discard an otherwise successful result.
    if ((init.method ?? 'GET').toUpperCase() === 'GET') {
      for (const delayMs of NETWORK_RETRY_DELAYS_MS) {
        await wait(delayMs)
        try {
          response = await request()
          retried = true
          break
        } catch {
          // Report only after the bounded retry budget is exhausted.
        }
      }
    }
    if (!response) throw reportApiError(error, '网络连接失败')
  }
  // 撞上部署重启窗口：按预算重试等待新 backend 就绪，用户无感
  if (response.status === 502 || response.status === 503) {
    for (const delayMs of GATEWAY_RETRY_DELAYS_MS) {
      await wait(delayMs)
      try {
        const retriedResponse = await request()
        response = retriedResponse
        retried = true
        if (retriedResponse.status !== 502 && retriedResponse.status !== 503) break
      } catch {
        // 窗口内连接被拒绝：保留上一次响应，继续按预算重试
      }
    }
  }
  if ((response.status === 401 || response.status === 403) && retry && !path.startsWith('/auth/')) {
    if (!intentionalLogout && (await refreshAccess())) return apiRequest<T>(path, init, false)
    if (intentionalLogout) throw new ApiError('已退出登录', response.status)
    forceLogout()
    throw reportApiError(new ApiError('登录已过期，请重新登录', response.status))
  }
  const t1 = tracked ? performance.now() : 0
  const body = await response.json().catch(() => ({}))
  if (tracked) {
    recordApiTiming({
      path,
      method: (init.method ?? 'GET').toUpperCase(),
      status: response.status,
      networkMs: Math.round(t1 - t0),
      parseMs: Math.round(performance.now() - t1),
      totalMs: Math.round(performance.now() - t0),
      retried,
    })
  }
  if (!response.ok)
    throw reportApiError(
      new ApiError(
        body.detail ||
          (response.status === 502 || response.status === 503
            ? '服务正在重启，请稍后重试'
            : `请求失败（HTTP ${response.status}）`),
        response.status,
        body.errorCode,
      ),
    )
  return body as T
}

export async function openApiStream(
  path: string,
  signal?: AbortSignal,
  retry = true,
  extraHeaders: Record<string, string> = {},
): Promise<Response> {
  const headers = new Headers(extraHeaders)
  if (accessToken) headers.set('Authorization', `Bearer ${accessToken}`)
  const tracked = !isPollingHeaders(headers)
  const t0 = tracked ? performance.now() : 0
  let response: Response
  try {
    response = await fetch(`/api${path}`, { headers, credentials: 'include', signal })
  } catch (error) {
    throw reportApiError(error, '实时进度连接失败')
  }
  if (tracked) {
    const t1 = performance.now()
    recordApiTiming({
      path,
      method: 'GET',
      status: response.status,
      networkMs: Math.round(t1 - t0),
      parseMs: 0,
      totalMs: Math.round(t1 - t0),
      retried: false,
    })
  }
  if ((response.status === 401 || response.status === 403) && retry) {
    if (!intentionalLogout && (await refreshAccess())) return openApiStream(path, signal, false, extraHeaders)
    if (intentionalLogout) throw new ApiError('已退出登录', response.status)
    forceLogout()
    throw reportApiError(new ApiError('登录已过期，请重新登录', response.status))
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw reportApiError(
      new ApiError(
        body.detail ||
          (response.status === 502 || response.status === 503
            ? '服务正在重启，请稍后重试'
            : `实时进度连接失败（HTTP ${response.status}）`),
        response.status,
        body.errorCode,
      ),
    )
  }
  return response
}
export interface AuthUser {
  id: string
  username: string
  displayName: string
  role: 'admin' | 'user'
  mustChangePassword: boolean
}
export async function loginRequest(username: string, password: string) {
  let response: Response
  try {
    response = await fetch('/api/auth/login', {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    })
  } catch (error) {
    throw reportApiError(error, '网络连接失败')
  }
  const body = await response.json().catch(() => ({}))
  if (!response.ok)
    throw reportApiError(new ApiError(body.detail || '登录失败', response.status, body.errorCode))
  setAccessToken(body.accessToken)
  intentionalLogout = false // 重新登录成功后，恢复正常的 401 会话处理
  return body as { accessToken: string; user: AuthUser }
}
export async function restoreSession(): Promise<AuthUser | null> {
  if (!(await refreshAccess())) return null
  return apiRequest<AuthUser>('/auth/me')
}
export async function logoutRequest() {
  intentionalLogout = true
  await apiRequest('/auth/logout', { method: 'POST' }, false).catch(() => undefined)
  setAccessToken('')
}
