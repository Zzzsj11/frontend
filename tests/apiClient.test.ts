import { afterEach, describe, expect, it, vi } from 'vitest'

import { apiRequest, setAccessToken } from '../src/api/client'

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
