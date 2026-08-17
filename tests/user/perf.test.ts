import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ApiTiming } from '../../src/perf'

/** 动态 import 保证 apiRequest 与 perf buffer 是同一模块实例（静态 import 会实例分离） */
const fresh = () => import('../../src/perf')
const freshClient = () => import('../../src/api/client')

const timing = (path: string, totalMs: number, extra: Partial<ApiTiming> = {}): ApiTiming => ({
  path,
  method: 'GET',
  status: 200,
  networkMs: Math.min(totalMs, 100),
  parseMs: Math.max(0, totalMs - 100),
  totalMs,
  retried: false,
  id: 0,
  at: 0,
  ...extra,
})

describe('perf ring buffer aggregation', () => {
  beforeEach(() => {
    vi.resetModules()
  })

  it('aggregates API timings by path with count/avg/p95/max sorted by max desc', async () => {
    const perf = await fresh()
    // 5 次请求：1 次 100ms、3 次 200ms、1 次 500ms → avg=220, p95=500, max=500
    for (let i = 0; i < 5; i++) {
      perf.recordApiTiming(timing('/api/tasks/t1', [100, 200, 200, 200, 500][i]))
    }
    perf.recordApiTiming(timing('/api/digital-humans', 3000))
    const summary = perf.apiTimingSummary()
    expect(summary[0].path).toBe('/api/digital-humans')
    expect(summary[0].maxMs).toBe(3000)
    const task = summary.find((row) => row.path === '/api/tasks/t1')!
    expect(task.count).toBe(5)
    expect(task.avgMs).toBe(240)
    expect(task.p95Ms).toBe(500)
    expect(task.maxMs).toBe(500)
  })

  it('filters slow API entries by threshold', async () => {
    const perf = await fresh()
    perf.recordApiTiming(timing('/api/a', 200))
    perf.recordApiTiming(timing('/api/b', 1200, { retried: true }))
    const slow = perf.recentSlowApi(800)
    expect(slow).toHaveLength(1)
    expect(slow[0].path).toBe('/api/b')
    expect(slow[0].retried).toBe(true)
  })

  it('isPollingHeaders detects the X-Polling marker', async () => {
    const perf = await fresh()
    expect(perf.isPollingHeaders({ 'X-Polling': '1' })).toBe(true)
    expect(perf.isPollingHeaders({ 'X-Polling': '0' })).toBe(false)
    expect(perf.isPollingHeaders(undefined)).toBe(false)
  })
})

describe('apiRequest performance instrumentation', () => {
  beforeEach(() => {
    vi.resetModules()
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.resetModules()
  })

  it('records timing for normal requests and skips polling requests', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ ok: true }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      ),
    )
    const client = await freshClient()
    client.setAccessToken('')
    await client.apiRequest('/tasks/t1')
    await client.apiRequest('/tasks/t1', { headers: { 'X-Polling': '1' } })
    const perf = await fresh()
    const entries = perf.perfSnapshot().apiEntries
    expect(entries).toHaveLength(1)
    expect(entries[0].path).toBe('/tasks/t1')
    expect(entries[0].method).toBe('GET')
    expect(entries[0].status).toBe(200)
    expect(entries[0].totalMs).toBeGreaterThanOrEqual(0)
    expect(entries[0].networkMs).toBeGreaterThanOrEqual(0)
    expect(entries[0].parseMs).toBeGreaterThanOrEqual(0)
    expect(entries[0].retried).toBe(false)
  })
})
