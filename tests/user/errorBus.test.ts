import { beforeEach, describe, expect, it } from 'vitest'
import { ApiError, errorBus, reportApiError } from '../../src/errorBus'

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
})
