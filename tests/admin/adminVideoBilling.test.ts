import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import AdminVideoBillingPanel from '../../src/components/AdminVideoBillingPanel.vue'

const { apiRequest } = vi.hoisted(() => ({ apiRequest: vi.fn() }))
vi.mock('../../src/api/client', () => ({ apiRequest }))

const response = {
  total: 2,
  models: ['minimax-h3'],
  summary: {
    totalAmount: 5.1,
    pricedRecords: 1,
    failedRecords: 2,
    failedAmount: 5.1,
    excludedRecords: 1,
    unpricedRecords: 0,
    noUsageRecords: 0,
  },
  items: [
    {
      id: 'bill-1',
      generationJobId: 'job-1',
      username: 'dev01',
      projectName: '项目A',
      taskTitle: '子项目A',
      provider: 'yinghe-h3',
      model: 'minimax-h3',
      resolution: '720p',
      generationStatus: 'failed',
      isFailed: true,
      billingStatus: 'priced',
      usageQuantity: 12,
      usageUnit: '秒',
      unitPrice: 0.425,
      amount: 5.1,
      currency: 'CNY',
      completedAt: '2026-08-25T00:00:00Z',
    },
    {
      id: 'bill-2',
      generationJobId: 'job-2',
      username: 'dev01',
      projectName: '项目A',
      taskTitle: '子项目B',
      provider: 'runninghub',
      model: 'minimax-h3-runninghub',
      resolution: '720p',
      generationStatus: 'failed',
      isFailed: true,
      billingStatus: 'excluded',
      usageQuantity: 80,
      usageUnit: 'RH币',
      unitPrice: 0,
      amount: 0,
      currency: 'CNY',
      completedAt: '2026-08-25T00:00:00Z',
    },
  ],
}

describe('AdminVideoBillingPanel', () => {
  beforeEach(() => {
    apiRequest.mockReset()
    apiRequest.mockResolvedValue(response)
  })

  it('显著展示失败任务、失败费用和排除渠道', async () => {
    const wrapper = mount(AdminVideoBillingPanel)
    await flushPromises()
    expect(wrapper.text()).toContain('最终失败任务')
    expect(wrapper.text()).toContain('失败任务费用')
    expect(wrapper.text()).toContain('¥5.100000')
    expect(wrapper.findAll('.badge.failed')).toHaveLength(2)
    expect(wrapper.text()).toContain('渠道暂不计费')
  })

  it('支持筛选失败任务并触发历史重算', async () => {
    const wrapper = mount(AdminVideoBillingPanel)
    await flushPromises()
    await wrapper.find('select').setValue('failed')
    await flushPromises()
    expect(apiRequest.mock.calls.at(-1)?.[0]).toContain('status=failed')
    apiRequest
      .mockResolvedValueOnce({ processed: 2, priced: 1, failed: 2 })
      .mockResolvedValueOnce(response)
    await wrapper.get('button.primary').trigger('click')
    await flushPromises()
    expect(apiRequest).toHaveBeenCalledWith('/admin/video-billing/reconcile', { method: 'POST' })
    expect(wrapper.text()).toContain('历史核算完成')
  })
})
