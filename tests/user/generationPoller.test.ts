import { describe, expect, it, vi } from 'vitest'
import { errorBus } from '../../src/errorBus'
import {
  PollingCancelledError,
  abortableSleep,
  cancelTaskWatchers,
  registerTaskWatcher,
  watchGenerationJob,
} from '../../src/utils/generationPoller'

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

describe('generationPoller 统一轮询调度器', () => {
  it('轮询到 succeeded 后按 select 提取结果，并携带 X-Polling 标记', async () => {
    const request = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValue(json([{ id: 'job-ok', status: 'succeeded', result: { url: '/a.png' } }]))

    const value = await watchGenerationJob<{ url: string }>('job-ok', {
      select: (snapshot) => snapshot.result as { url: string },
    })
    expect(value.url).toBe('/a.png')
    const call = request.mock.calls[0]
    expect(String(call[0])).toBe('/api/generations/status')
    expect(JSON.parse(String(call[1]?.body))).toEqual({ ids: ['job-ok'] })
    // apiRequest 会把 headers 归一为 Headers 实例
    expect((call[1]?.headers as Headers).get('X-Polling')).toBe('1')
    expect(String(request.mock.calls[1][0])).toBe('/api/generations/observed')
    expect(JSON.parse(String(request.mock.calls[1][1]?.body))).toEqual({ ids: ['job-ok'] })
  })

  it('相同工单的多个订阅都能结束，不覆盖原 Promise', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async () =>
      json([{ id: 'job-shared', status: 'succeeded', result: 'done' }]),
    )
    const results = await Promise.all([
      watchGenerationJob('job-shared', { select: (s) => s.result }),
      watchGenerationJob('job-shared', { select: (s) => s.result }),
    ])
    expect(results).toEqual(['done', 'done'])
  })

  it('临时网络故障后继续查询，直到后端返回成功', async () => {
    const showError = vi.spyOn(errorBus, 'show')
    const request = vi
      .spyOn(globalThis, 'fetch')
      .mockRejectedValueOnce(new TypeError('Failed to fetch'))
      .mockImplementation(async () =>
        json([{ id: 'job-retry-network', status: 'succeeded', result: 'recovered' }]),
      )
    await expect(
      watchGenerationJob('job-retry-network', { select: (s) => s.result, timeoutMs: 10000 }),
    ).resolves.toBe('recovered')
    expect(request.mock.calls.length).toBeGreaterThanOrEqual(2)
    expect(showError).not.toHaveBeenCalled()
  }, 10000)

  it('轮询到 failed 后以任务 error 文案 reject', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      json([{ id: 'job-fail', status: 'failed', error: '供应商拒绝' }]),
    )
    await expect(watchGenerationJob('job-fail', { select: (s) => s.result })).rejects.toThrow(
      '供应商拒绝',
    )
  })

  it('注册前 signal 已 abort 时立即 reject PollingCancelledError，不发起请求', async () => {
    const request = vi.spyOn(globalThis, 'fetch')
    const controller = new AbortController()
    controller.abort()
    await expect(
      watchGenerationJob('job-pre-abort', { signal: controller.signal, select: (s) => s.result }),
    ).rejects.toBeInstanceOf(PollingCancelledError)
    expect(request).not.toHaveBeenCalled()
  })

  it('请求在飞时 abort（fetch 抛 AbortError）时归一为 PollingCancelledError', async () => {
    // mock 模拟真实 fetch 的中止行为：已 abort 立即抛 AbortError，否则挂起直至 abort
    // （apiRequest 对主动取消不吃重试预算、不上报，AbortError 直达调度器归一）
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (_input, init) => {
      const signal = init?.signal
      if (signal?.aborted) throw new DOMException('aborted', 'AbortError')
      return new Promise<Response>((_resolve, reject) => {
        signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')))
      })
    })
    const controller = new AbortController()
    const promise = watchGenerationJob('job-inflight-abort', {
      signal: controller.signal,
      timeoutMs: 60_000,
      select: (s) => s.result,
    })
    // 等首查请求发出后 abort，在飞的 fetch 立即抛 AbortError，调度器归一为取消错误
    await vi.waitFor(() => expect(globalThis.fetch).toHaveBeenCalled())
    controller.abort()
    await expect(promise).rejects.toBeInstanceOf(PollingCancelledError)
  })

  it('任务长期 pending 超过 timeoutMs 后以超时文案 reject', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      json([{ id: 'job-timeout', status: 'running', progress: 5 }]),
    )
    await expect(
      watchGenerationJob('job-timeout', {
        timeoutMs: 1,
        select: (s) => s.result,
        timeoutMessage: '生成超时，请稍后重试',
      }),
    ).rejects.toThrow('生成超时，请稍后重试')
  })

  it('相隔 1 毫秒注册的任务共享同一首查窗口，按各自 ID 一次落定', async () => {
    vi.useFakeTimers()
    try {
      const groups: string[][] = []
      vi.spyOn(globalThis, 'fetch').mockImplementation(async (path, init) => {
        const { ids } = JSON.parse(String(init?.body)) as { ids: string[] }
        groups.push(ids)
        return path === '/api/generations/observed'
          ? json({})
          : json(ids.map((id) => ({ id, status: 'succeeded', result: id })))
      })
      const first = watchGenerationJob('job-multi-a', { select: (s) => s.result })
      await vi.advanceTimersByTimeAsync(1)
      const second = watchGenerationJob('job-multi-b', { select: (s) => s.result })
      await vi.advanceTimersByTimeAsync(49)
      const expected = ['job-multi-a', 'job-multi-b']
      expect(groups).toEqual([expected, expected])
      await expect(Promise.all([first, second])).resolves.toEqual(expected)
    } finally {
      vi.useRealTimers()
    }
  })
})

describe('taskWatchers 子项目 watcher 注册表', () => {
  it('cancelTaskWatchers 中止该子项目全部 watcher 并清理注册表', () => {
    const a = registerTaskWatcher('task-x')
    const b = registerTaskWatcher('task-x')
    const other = registerTaskWatcher('task-y')
    cancelTaskWatchers('task-x')
    expect(a.signal.aborted).toBe(true)
    expect(b.signal.aborted).toBe(true)
    expect(other.signal.aborted).toBe(false)
    // 清理后可重新注册同名子项目
    const again = registerTaskWatcher('task-x')
    expect(again.signal.aborted).toBe(false)
  })

  it('单个 watcher abort 后自动从注册表移除', () => {
    const controller = registerTaskWatcher('task-z')
    controller.abort()
    // 再次 cancel 不应报错（注册表已空）
    expect(() => cancelTaskWatchers('task-z')).not.toThrow()
  })
})

describe('abortableSleep', () => {
  it('signal 未 abort 时到时返回', async () => {
    const started = Date.now()
    await abortableSleep(30)
    expect(Date.now() - started).toBeGreaterThanOrEqual(20)
  })

  it('signal 已 abort 时立即返回', async () => {
    const controller = new AbortController()
    controller.abort()
    const started = Date.now()
    await abortableSleep(5000, controller.signal)
    expect(Date.now() - started).toBeLessThan(100)
  })

  it('sleep 中途 abort 时提前返回', async () => {
    const controller = new AbortController()
    const started = Date.now()
    setTimeout(() => controller.abort(), 20)
    await abortableSleep(5000, controller.signal)
    expect(Date.now() - started).toBeLessThan(1000)
  })
})

describe('bounded status observation', () => {
  it('honors the server retry window even after the first status request fails', async () => {
    vi.useFakeTimers()
    try {
      let statusCalls = 0
      vi.spyOn(globalThis, 'fetch').mockImplementation(async (path) => {
        if (path === '/api/generations/observed') return json({})
        statusCalls++
        return statusCalls === 1
          ? new Response('{}', { status: 429, headers: { 'Retry-After': '8' } })
          : json([{ id: 'rate-limit', status: 'succeeded', result: 'done' }])
      })
      const result = watchGenerationJob('rate-limit', { select: (s) => s.result })
      await vi.advanceTimersByTimeAsync(50)
      await vi.advanceTimersByTimeAsync(7999)
      expect(statusCalls).toBe(1)
      await vi.advanceTimersByTimeAsync(1)
      await expect(result).resolves.toBe('done')
      expect(statusCalls).toBe(2)
    } finally {
      vi.useRealTimers()
    }
  })

  it('delivers 501 simultaneous subscriptions in two bounded requests', async () => {
    vi.useFakeTimers()
    try {
      const groups: string[][] = []
      vi.spyOn(globalThis, 'fetch').mockImplementation(async (path, init) => {
        if (path === '/api/generations/observed') return json({})
        const ids: string[] = JSON.parse(String(init?.body)).ids
        groups.push(ids)
        return json(ids.map((id) => ({ id, status: 'succeeded', result: id })))
      })
      const ids = Array.from({ length: 501 }, (_, i) => 'job-' + i)
      const results = Promise.all(
        ids.map((id) => watchGenerationJob(id, { select: (snapshot) => snapshot.result })),
      )
      await vi.advanceTimersByTimeAsync(50)
      await expect(results).resolves.toEqual(ids)
      expect(groups.map((group) => group.length)).toEqual([500, 1])
    } finally {
      vi.useRealTimers()
    }
  })

  it('a hung status fetch times out and a hung observation receipt never blocks delivery', async () => {
    vi.useFakeTimers()
    try {
      let statusCalls = 0
      vi.spyOn(globalThis, 'fetch').mockImplementation(async (path, init) => {
        if (path === '/api/generations/status' && ++statusCalls === 2)
          return json([{ id: 'bounded', status: 'succeeded', result: 'ok' }])
        return new Promise<Response>((_resolve, reject) =>
          init!.signal!.addEventListener(
            'abort',
            () => reject(new DOMException('Aborted', 'AbortError')),
            { once: true },
          ),
        )
      })
      const result = watchGenerationJob('bounded', { select: (s) => s.result })
      await vi.advanceTimersByTimeAsync(50 + 12000 + 3000)
      expect(statusCalls).toBe(2)
      await expect(result).resolves.toBe('ok')
    } finally {
      vi.useRealTimers()
    }
  })
})
