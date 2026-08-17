import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  apiRequest,
  logoutRequest,
  openApiStream,
  resetAuthState,
  setAccessToken,
} from '../../src/api/client'
import { errorBus } from '../../src/errorBus'

describe('apiRequest', () => {
  afterEach(() => {
    setAccessToken('')
    vi.useRealTimers()
  })

  it('retries transient GET network failures without surfacing an error', async () => {
    vi.useFakeTimers()
    const fetchMock = vi
      .spyOn(globalThis, 'fetch')
      .mockRejectedValueOnce(new TypeError('Failed to fetch'))
      .mockRejectedValueOnce(new TypeError('Failed to fetch'))
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ status: 'succeeded' }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      )

    const resultPromise = apiRequest<{ status: string }>('/generations/job-1')
    await vi.runAllTimersAsync()

    await expect(resultPromise).resolves.toEqual({ status: 'succeeded' })
    expect(fetchMock).toHaveBeenCalledTimes(3)
  })

  it('does not replay a mutating request after an uncertain network failure', async () => {
    const fetchMock = vi
      .spyOn(globalThis, 'fetch')
      .mockRejectedValueOnce(new TypeError('Failed to fetch'))

    await expect(apiRequest('/generations/videos', { method: 'POST' })).rejects.toThrow(
      '网络连接失败',
    )
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('retries POST requests that hit a 502 gateway window', async () => {
    vi.useFakeTimers()
    const fetchMock = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(new Response('Bad Gateway', { status: 502 }))
      .mockResolvedValueOnce(new Response('Bad Gateway', { status: 502 }))
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ id: 'job-1' }), {
          status: 202,
          headers: { 'Content-Type': 'application/json' },
        }),
      )

    const resultPromise = apiRequest<{ id: string }>('/generations/videos', { method: 'POST' })
    await vi.runAllTimersAsync()

    await expect(resultPromise).resolves.toEqual({ id: 'job-1' })
    expect(fetchMock).toHaveBeenCalledTimes(3)
  })

  it('surfaces an actionable message after the 502 retry budget is exhausted', async () => {
    vi.useFakeTimers()
    const fetchMock = vi
      .spyOn(globalThis, 'fetch')
      .mockImplementation(async () => new Response('Bad Gateway', { status: 502 }))

    const resultPromise = apiRequest('/generations/videos', { method: 'POST' })
    const assertion = expect(resultPromise).rejects.toThrow('服务正在重启，请稍后重试')
    await vi.runAllTimersAsync()
    await assertion
    expect(fetchMock).toHaveBeenCalledTimes(5)
  })
})

describe('apiRequest 主动取消（abort）', () => {
  const expectAbort = async (promise: Promise<unknown>) => {
    const failure = await promise.catch((error: unknown) => error)
    expect(failure).toBeInstanceOf(DOMException)
    expect((failure as DOMException).name).toBe('AbortError')
  }

  beforeEach(() => {
    // errorBus 是模块级单例：清掉前面用例（如网络重试耗尽）合法上报的存量弹窗
    errorBus.dismissAll()
  })

  afterEach(() => {
    errorBus.dismissAll()
  })

  it('已 abort 的 GET 立即失败：不吃网络重试预算、不上报错误弹窗', async () => {
    const controller = new AbortController()
    controller.abort()
    const fetchMock = vi
      .spyOn(globalThis, 'fetch')
      .mockRejectedValue(new DOMException('aborted', 'AbortError'))

    await expectAbort(apiRequest('/generations/job-1', { signal: controller.signal }))
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(errorBus.state.queue).toHaveLength(0)
  })

  it('网络重试等待期间 abort：立即退出预算，不再补发请求', async () => {
    const controller = new AbortController()
    const fetchMock = vi
      .spyOn(globalThis, 'fetch')
      .mockRejectedValueOnce(new TypeError('Failed to fetch'))
      .mockRejectedValue(new DOMException('aborted', 'AbortError'))

    const started = Date.now()
    const promise = apiRequest('/generations/job-1', { signal: controller.signal })
    // 首次失败进入 500ms 重试等待，等待期间 abort
    setTimeout(() => controller.abort(), 30)
    await expectAbort(promise)
    expect(Date.now() - started).toBeLessThan(400)
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(errorBus.state.queue).toHaveLength(0)
  })

  it('502 网关重试窗口期间 abort：退出等待且不上报', async () => {
    const controller = new AbortController()
    const fetchMock = vi
      .spyOn(globalThis, 'fetch')
      .mockImplementation(async () => new Response('Bad Gateway', { status: 502 }))

    const started = Date.now()
    const promise = apiRequest('/generations/videos', {
      method: 'POST',
      signal: controller.signal,
    })
    // 首个网关等待为 1000ms，等待期间 abort
    setTimeout(() => controller.abort(), 30)
    await expectAbort(promise)
    expect(Date.now() - started).toBeLessThan(900)
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(errorBus.state.queue).toHaveLength(0)
  })

  it('openApiStream 被 abort 时静默抛出，不上报错误弹窗', async () => {
    const controller = new AbortController()
    controller.abort()
    vi.spyOn(globalThis, 'fetch').mockRejectedValue(new DOMException('aborted', 'AbortError'))

    await expectAbort(openApiStream('/tasks/task-1/outline-events', controller.signal))
    expect(errorBus.state.queue).toHaveLength(0)
  })
})

describe('apiRequest auth recovery (401/403)', () => {
  const realLocation = Object.getOwnPropertyDescriptor(window, 'location')!
  const mockLocation = { pathname: '/projects', search: '?tab=1', href: '' }

  const jsonResponse = (body: unknown, status = 200) =>
    new Response(JSON.stringify(body), {
      status,
      headers: { 'Content-Type': 'application/json' },
    })

  beforeEach(() => {
    mockLocation.pathname = '/projects'
    mockLocation.search = '?tab=1'
    mockLocation.href = ''
    Object.defineProperty(window, 'location', { configurable: true, value: mockLocation })
  })

  afterEach(() => {
    Object.defineProperty(window, 'location', realLocation)
    resetAuthState()
  })

  it('replays the request with the refreshed token after a 401', async () => {
    setAccessToken('old-token')
    const calls: { url: string; auth: string | null }[] = []
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = String(input)
      const auth = new Headers(init?.headers).get('Authorization')
      calls.push({ url, auth })
      if (url === '/api/auth/refresh') return jsonResponse({ accessToken: 'new-token' })
      if (auth === 'Bearer new-token') return jsonResponse({ ok: true })
      return jsonResponse({ detail: 'token expired' }, 401)
    })

    await expect(apiRequest<{ ok: boolean }>('/projects')).resolves.toEqual({ ok: true })
    expect(calls.map((call) => call.url)).toEqual([
      '/api/projects',
      '/api/auth/refresh',
      '/api/projects',
    ])
    expect(calls[0].auth).toBe('Bearer old-token')
    expect(calls[2].auth).toBe('Bearer new-token')
    expect(mockLocation.href).toBe('')
  })

  it('treats 403 the same way: refresh then replay', async () => {
    setAccessToken('old-token')
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = String(input)
      if (url === '/api/auth/refresh') return jsonResponse({ accessToken: 'new-token' })
      const auth = new Headers(init?.headers).get('Authorization')
      if (auth === 'Bearer new-token') return jsonResponse({ ok: true })
      return jsonResponse({ detail: 'forbidden' }, 403)
    })

    await expect(apiRequest<{ ok: boolean }>('/projects')).resolves.toEqual({ ok: true })
  })

  it('forces logout with login redirect when the refresh fails', async () => {
    setAccessToken('old-token')
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
      const url = String(input)
      if (url === '/api/auth/refresh') return jsonResponse({ detail: 'refresh expired' }, 401)
      return jsonResponse({ detail: 'token expired' }, 401)
    })

    await expect(apiRequest('/projects')).rejects.toThrow('登录已过期，请重新登录')
    expect(mockLocation.href).toBe(`/login?redirect=${encodeURIComponent('/projects?tab=1')}`)
    // token 已清空：后续请求不再携带 Authorization
    fetchMock.mockClear()
    fetchMock.mockImplementation(async () => jsonResponse({ ok: true }))
    await apiRequest('/projects')
    expect(new Headers(fetchMock.mock.calls[0][1]?.headers).get('Authorization')).toBeNull()
  })

  it('does not attempt a refresh for /auth/ endpoints', async () => {
    setAccessToken('old-token')
    const fetchMock = vi
      .spyOn(globalThis, 'fetch')
      .mockImplementation(async () => jsonResponse({ detail: '用户名或密码错误' }, 401))

    await expect(apiRequest('/auth/login', { method: 'POST' })).rejects.toThrow('用户名或密码错误')
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(mockLocation.href).toBe('')
  })

  it('fails silently for in-flight requests after an intentional logout', async () => {
    setAccessToken('old-token')
    const fetchMock = vi
      .spyOn(globalThis, 'fetch')
      .mockImplementation(async () => jsonResponse({ detail: 'token expired' }, 401))

    await logoutRequest()
    // 退出后任何在途请求撞 401：不尝试 refresh、不弹“登录已过期”、不强制跳转
    fetchMock.mockClear()
    await expect(apiRequest('/projects')).rejects.toThrow('已退出登录')
    expect(fetchMock).not.toHaveBeenCalledWith('/api/auth/refresh', expect.anything())
    expect(mockLocation.href).toBe('')
  })

  it('does not redirect again when already on the login page', async () => {
    mockLocation.pathname = '/login'
    mockLocation.search = ''
    setAccessToken('old-token')
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
      const url = String(input)
      if (url === '/api/auth/refresh') return jsonResponse({ detail: 'refresh expired' }, 401)
      return jsonResponse({ detail: 'token expired' }, 401)
    })

    await expect(apiRequest('/projects')).rejects.toThrow('登录已过期，请重新登录')
    // 防循环 redirect：已在 /login 页时 href 不被覆写
    expect(mockLocation.href).toBe('')
  })

  it('shares a single refresh across concurrent unauthorized requests', async () => {
    setAccessToken('old-token')
    let refreshCalls = 0
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = String(input)
      if (url === '/api/auth/refresh') {
        refreshCalls += 1
        // 拉长刷新窗口，保证两个请求的重叠期撞上同一个 refreshPromise
        await new Promise((resolve) => setTimeout(resolve, 10))
        return jsonResponse({ accessToken: 'new-token' })
      }
      const auth = new Headers(init?.headers).get('Authorization')
      if (auth === 'Bearer new-token') return jsonResponse({ ok: true })
      return jsonResponse({ detail: 'token expired' }, 401)
    })

    await expect(
      Promise.all([apiRequest('/projects'), apiRequest('/digital-humans')]),
    ).resolves.toEqual([{ ok: true }, { ok: true }])
    expect(refreshCalls).toBe(1)
  })

  it('surfaces the replay response error without looping when the new token is also rejected', async () => {
    setAccessToken('old-token')
    let calls = 0
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
      calls += 1
      const url = String(input)
      if (url === '/api/auth/refresh') return jsonResponse({ accessToken: 'new-token' })
      return jsonResponse({ detail: 'still unauthorized' }, 401)
    })

    // 重放（retry=false）不再触发刷新，直接抛出服务端返回的错误，避免无限刷新循环
    await expect(apiRequest('/projects')).rejects.toThrow('still unauthorized')
    expect(calls).toBe(3)
    expect(mockLocation.href).toBe('')
  })
})

describe('openApiStream auth recovery (401/403)', () => {
  const realLocation = Object.getOwnPropertyDescriptor(window, 'location')!
  const mockLocation = { pathname: '/projects', search: '?tab=1', href: '' }

  const jsonResponse = (body: unknown, status = 200) =>
    new Response(JSON.stringify(body), {
      status,
      headers: { 'Content-Type': 'application/json' },
    })

  beforeEach(() => {
    mockLocation.pathname = '/projects'
    mockLocation.search = '?tab=1'
    mockLocation.href = ''
    Object.defineProperty(window, 'location', { configurable: true, value: mockLocation })
  })

  afterEach(() => {
    Object.defineProperty(window, 'location', realLocation)
    resetAuthState()
  })

  it('re-opens the stream with the refreshed token after a 401', async () => {
    setAccessToken('old-token')
    const calls: { url: string; auth: string | null }[] = []
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = String(input)
      const auth = new Headers(init?.headers).get('Authorization')
      calls.push({ url, auth })
      if (url === '/api/auth/refresh') return jsonResponse({ accessToken: 'new-token' })
      if (auth === 'Bearer new-token')
        return new Response('data: {}\n\n', {
          status: 200,
          headers: { 'Content-Type': 'text/event-stream' },
        })
      return jsonResponse({ detail: 'token expired' }, 401)
    })

    const response = await openApiStream('/tasks/task-1/outline-events')
    expect(response.status).toBe(200)
    expect(calls.map((call) => call.url)).toEqual([
      '/api/tasks/task-1/outline-events',
      '/api/auth/refresh',
      '/api/tasks/task-1/outline-events',
    ])
    expect(calls[2].auth).toBe('Bearer new-token')
    expect(mockLocation.href).toBe('')
  })

  it('forces logout with login redirect when the stream refresh fails', async () => {
    setAccessToken('old-token')
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
      const url = String(input)
      if (url === '/api/auth/refresh') return jsonResponse({ detail: 'refresh expired' }, 401)
      return jsonResponse({ detail: 'forbidden' }, 403)
    })

    await expect(openApiStream('/tasks/task-1/outline-events')).rejects.toThrow(
      '登录已过期，请重新登录',
    )
    expect(mockLocation.href).toBe(`/login?redirect=${encodeURIComponent('/projects?tab=1')}`)
  })
})
