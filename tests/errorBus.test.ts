import { beforeEach, describe, expect, it } from 'vitest'
import { ApiError, errorBus, reportApiError } from '../src/errorBus'

describe('global error dialog queue', () => {
  beforeEach(() => { errorBus.state.queue = []; errorBus.state.nextId = 1 })
  it('keeps tracking code and deduplicates concurrent identical errors', () => {
    reportApiError(new ApiError('分镜生成失败', 502, 'ERR-ABC'))
    reportApiError(new ApiError('分镜生成失败', 502, 'ERR-ABC'))
    expect(errorBus.state.queue).toHaveLength(1)
    expect(errorBus.state.queue[0]).toMatchObject({ errorCode: 'ERR-ABC', status: 502, title: '服务异常' })
  })
})
