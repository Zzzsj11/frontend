import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ErrorDialog from '../../src/components/ErrorDialog.vue'
import { ApiError, classifyErrorMessage, errorBus, reportApiError } from '../../src/errorBus'

describe('global error dialog queue', () => {
  beforeEach(() => {
    errorBus.state.queue = []
    errorBus.state.nextId = 1
  })
  it('keeps tracking code and deduplicates concurrent identical errors', () => {
    reportApiError(new ApiError('分镜生成失败', 502, 'ERR-ABC'))
    reportApiError(new ApiError('分镜生成失败', 502, 'ERR-ABC'))
    expect(errorBus.state.queue).toHaveLength(1)
    expect(errorBus.state.queue[0]).toMatchObject({
      errorCode: 'ERR-ABC',
      status: 502,
      title: '服务异常',
      repeatCount: 2,
    })
  })
  it('translates browser-owned network errors but preserves upstream API messages', () => {
    expect(reportApiError(new TypeError('Failed to fetch'), '网络连接失败').message).toBe(
      '网络连接失败',
    )
    expect(reportApiError(new ApiError('Request timed out.', 502)).message).toBe(
      'Request timed out.',
    )
  })
  it('classifies batch failures into actionable groups', () => {
    expect(classifyErrorMessage('output video may contain sensitive information').category).toBe(
      'content_safety',
    )
    expect(classifyErrorMessage('供应商创建接口经同一幂等键恢复后仍无法确认结果').category).toBe(
      'provider_submission',
    )
    expect(classifyErrorMessage('子账号余额不足').category).toBe('balance')
  })
  it('renders an aggregated batch summary and copies complete details', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } })
    errorBus.show({ title: '操作未完成', message: '内容未通过平台安全合规校验' })
    errorBus.show({ title: '操作未完成', message: '内容未通过平台安全合规校验' })
    errorBus.show({ title: '操作未完成', message: '供应商创建接口无法确认结果' })
    const wrapper = mount(ErrorDialog, { attachTo: document.body })

    expect(document.body.textContent).toContain('批量操作部分失败')
    expect(document.body.textContent).toContain('内容安全校验')
    expect(document.body.textContent).toContain('2 条')
    document.querySelector<HTMLButtonElement>('.detail-toggle')?.click()
    await flushPromises()
    expect(document.body.textContent).toContain('重复 2 次')
    document.querySelector<HTMLButtonElement>('.dismiss-all')?.click()
    await flushPromises()
    expect(writeText).toHaveBeenCalledOnce()
    expect(writeText.mock.calls[0][0]).toContain('重复 2 次')
    wrapper.unmount()
  })
})
