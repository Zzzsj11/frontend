import { describe, expect, it, vi } from 'vitest'
import {
  PollingCancelledError,
  abortableSleep,
  cancelTaskWatchers,
  registerTaskWatcher,
  watchGenerationJob,
} from '../src/utils/generationPoller'

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

describe('generationPoller 统一轮询调度器', () => {
  it('轮询到 succeeded 后按 select 提取结果，并携带 X-Polling 标记', async () => {
    const request = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValue(json({ id: 'job-ok', status: 'succeeded', result: { url: '/a.png' } }))

    const value = await watchGenerationJob<{ url: string }>('job-ok', {
      select: (snapshot) => snapshot.result as { url: string },
    })
    expect(value.url).toBe('/a.png')
    const call = request.mock.calls[0]
    expect(String(call[0])).toBe('/api/generations/job-ok')
    // apiRequest 会把 headers 归一为 Headers 实例
    expect((call[1]?.headers as Headers).get('X-Polling')).toBe('1')
  })

  it('轮询到 failed 后以任务 error 文案 reject', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      json({ id: 'job-fail', status: 'failed', error: '供应商拒绝' }),
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
    // （apiRequest 对 GET 有网络重试预算，重试时会以已 abort 的 signal 再次调用 fetch）
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
    // 等首查请求发出后 abort；apiRequest 重试预算（0.5s+1.5s）耗尽后由调度器归一为取消错误
    await vi.waitFor(() => expect(globalThis.fetch).toHaveBeenCalled())
    controller.abort()
    await expect(promise).rejects.toBeInstanceOf(PollingCancelledError)
  }, 8_000)

  it('任务长期 pending 超过 timeoutMs 后以超时文案 reject', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      json({ id: 'job-timeout', status: 'running', progress: 5 }),
    )
    await expect(
      watchGenerationJob('job-timeout', {
        timeoutMs: 1,
        select: (s) => s.result,
        timeoutMessage: '生成超时，请稍后重试',
      }),
    ).rejects.toThrow('生成超时，请稍后重试')
  })

  it('多个任务共享调度：同周期内串行查询并各自独立落定', async () => {
    const seen: string[] = []
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
      const url = String(input)
      seen.push(url)
      if (url.endsWith('job-multi-a'))
        return json({ id: 'job-multi-a', status: 'succeeded', result: 'A' })
      return json({ id: 'job-multi-b', status: 'succeeded', result: 'B' })
    })
    const [a, b] = await Promise.all([
      watchGenerationJob('job-multi-a', { select: (s) => s.result as string }),
      watchGenerationJob('job-multi-b', { select: (s) => s.result as string }),
    ])
    expect([a, b]).toEqual(['A', 'B'])
    expect(seen).toContain('/api/generations/job-multi-a')
    expect(seen).toContain('/api/generations/job-multi-b')
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
