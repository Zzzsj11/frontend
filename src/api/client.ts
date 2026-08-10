import { ApiError, reportApiError } from '../errorBus'

let accessToken = ''
let refreshPromise: Promise<boolean> | null = null
const NETWORK_RETRY_DELAYS_MS = [500, 1500]
const wait = (delayMs: number) => new Promise((resolve) => setTimeout(resolve, delayMs))
export const setAccessToken = (value: string) => { accessToken = value }
const refreshAccess = async () => {
  if (!refreshPromise) refreshPromise = fetch('/api/auth/refresh', { method: 'POST', credentials: 'include' }).then(async (response) => {
    if (!response.ok) return false
    setAccessToken(((await response.json()) as { accessToken: string }).accessToken)
    return true
  }).finally(() => { refreshPromise = null })
  return refreshPromise
}
export async function apiRequest<T>(path: string, init: RequestInit = {}, retry = true): Promise<T> {
  const headers = new Headers(init.headers)
  if (accessToken) headers.set('Authorization', `Bearer ${accessToken}`)
  if (init.body && !(init.body instanceof FormData) && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json')
  let response: Response | undefined
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
          break
        } catch {
          // Report only after the bounded retry budget is exhausted.
        }
      }
    }
    if (!response) throw reportApiError(error, '网络连接失败')
  }
  if (response.status === 401 && retry && !path.startsWith('/auth/') && await refreshAccess()) return apiRequest<T>(path, init, false)
  const body = await response.json().catch(() => ({}))
  if (!response.ok) throw reportApiError(new ApiError(body.detail || `请求失败（HTTP ${response.status}）`, response.status, body.errorCode))
  return body as T
}

export async function openApiStream(path: string, signal?: AbortSignal, retry = true): Promise<Response> {
  const headers = new Headers()
  if (accessToken) headers.set('Authorization', `Bearer ${accessToken}`)
  let response: Response
  try {
    response = await fetch(`/api${path}`, { headers, credentials: 'include', signal })
  } catch (error) {
    throw reportApiError(error, '实时进度连接失败')
  }
  if (response.status === 401 && retry && await refreshAccess()) return openApiStream(path, signal, false)
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw reportApiError(new ApiError(body.detail || `实时进度连接失败（HTTP ${response.status}）`, response.status, body.errorCode))
  }
  return response
}
export interface AuthUser { id: string; username: string; displayName: string; role: 'admin' | 'user'; mustChangePassword: boolean }
export async function loginRequest(username: string, password: string) {
  let response: Response
  try { response = await fetch('/api/auth/login', { method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ username, password }) }) }
  catch (error) { throw reportApiError(error, '网络连接失败') }
  const body = await response.json().catch(() => ({}))
  if (!response.ok) throw reportApiError(new ApiError(body.detail || '登录失败', response.status, body.errorCode))
  setAccessToken(body.accessToken)
  return body as { accessToken: string; user: AuthUser }
}
export async function restoreSession(): Promise<AuthUser | null> {
  if (!(await refreshAccess())) return null
  return apiRequest<AuthUser>('/auth/me')
}
export async function logoutRequest() {
  await apiRequest('/auth/logout', { method: 'POST' }, false).catch(() => undefined)
  setAccessToken('')
}
