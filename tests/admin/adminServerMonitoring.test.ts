import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { dryRunServerMaintenance, fetchServerMonitoring } from '../../src/api/adminServerMonitoring'
import AdminServerMonitoringPanel from '../../src/components/AdminServerMonitoringPanel.vue'

vi.mock('../../src/api/adminServerMonitoring', () => ({
  fetchServerMonitoring: vi.fn(),
  dryRunServerMaintenance: vi.fn(),
}))

const sample = {
  capturedAt: '2026-08-17T12:00:00Z',
  cpuPercent: 24.5,
  load: [0.2, 0.3, 0.4] as [number, number, number],
  memoryUsedPercent: 50,
  memoryTotalBytes: 16 * 1024 ** 3,
  memoryAvailableBytes: 8 * 1024 ** 3,
  diskUsedPercent: 25,
  diskTotalBytes: 100 * 1024 ** 3,
  diskAvailableBytes: 75 * 1024 ** 3,
  networkTxBps: 1_000_000,
  networkRxBps: 2_000_000,
  interface: 'eth0',
  containers: [],
  workloads: {
    queues: [{ kind: 'video', queued: 2, running: 2, oldestQueuedSeconds: 120 }],
    completedLastHour: [
      {
        kind: 'video',
        success: 8,
        failed: 1,
        queue_wait_seconds: { avg: 60, p95: 120 },
        execution_seconds: { avg: 10, p95: 14.4 },
        end_to_end_seconds: { avg: 74, p95: 137.4 },
        observationCoveragePercent: 88.9,
      },
    ],
    llmLastHour: { calls: 10, failed: 0, tokens: 1000, avgMs: 1000, p95Ms: 1500 },
    configuredExecutionLimits: { video: 2 },
  },
}

const summary = {
  latest: sample,
  points: [sample],
  stale: false,
  traffic: {
    month: '2026-08-01',
    quotaBytes: 300 * 1024 ** 3,
    egressBytes: 30 * 1024 ** 3,
    remainingBytes: 270 * 1024 ** 3,
    usedPercent: 10,
    accounting: 'public-egress' as const,
    unit: 'GiB' as const,
    reset: 'calendar-month' as const,
  },
  alerts: [],
  maintenanceRuns: [],
}

describe('admin server monitoring panel', () => {
  beforeEach(() => {
    vi.mocked(fetchServerMonitoring).mockReset()
    vi.mocked(fetchServerMonitoring).mockResolvedValue(summary)
    vi.mocked(dryRunServerMaintenance).mockReset()
    vi.mocked(dryRunServerMaintenance).mockResolvedValue({
      id: 'maintenance-1',
      status: 'analyzed',
      dryRun: true,
      summary: '仅分析，未执行删除',
    })
  })

  it('renders resource and natural-month public-egress accounting', async () => {
    const wrapper = mount(AdminServerMonitoringPanel)
    await vi.waitFor(() => expect(wrapper.text()).toContain('24.5%'))
    expect(wrapper.text()).toContain('月流量仅统计公网出站 · 自然月 300 GiB')
    expect(wrapper.text()).toContain('30.00 GiB')
    expect(wrapper.text()).toContain('270.00 GiB')
    expect(wrapper.text()).toContain('2026-08-01 自然月')
    expect(wrapper.text()).toContain('排队 P95')
    expect(wrapper.text()).toContain('2.0 分')
    expect(wrapper.text()).toContain('14 秒')
    expect(wrapper.text()).toContain('2.3 分')
    expect(wrapper.text()).toContain('89%')
    wrapper.unmount()
  })

  it('runs only an explicit dry-run maintenance analysis', async () => {
    const wrapper = mount(AdminServerMonitoringPanel)
    await vi.waitFor(() => expect(wrapper.text()).toContain('安全维护分析'))
    await wrapper.get('.maintenance-actions button').trigger('click')
    await vi.waitFor(() =>
      expect(dryRunServerMaintenance).toHaveBeenCalledWith('cleanup_temp_files'),
    )
    expect(fetchServerMonitoring).toHaveBeenCalledTimes(2)
    wrapper.unmount()
  })
})
