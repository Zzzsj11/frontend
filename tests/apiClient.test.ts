import { afterEach, describe, expect, it, vi } from 'vitest'

import { apiRequest, setAccessToken } from '../src/api/client'

describe('apiRequest', () => {
  afterEach(() => {
    setAccessToken('')
    vi.useRealTimers()
  })

  it('retries transient GET network failures without surfacing an error', async () => {
    vi.useFakeTimers()
    const fetchMock = vi.spyOn(globalThis, 'fetch')
      .mockRejectedValueOnce(new TypeError('Failed to fetch'))
      .mockRejectedValueOnce(new TypeError('Failed to fetch'))
      .mockResolvedValueOnce(new Response(JSON.stringify({ status: 'succeeded' }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }))

    const resultPromise = apiRequest<{ status: string }>('/generations/job-1')
    await vi.runAllTimersAsync()

    await expect(resultPromise).resolves.toEqual({ status: 'succeeded' })
    expect(fetchMock).toHaveBeenCalledTimes(3)
  })

  it('does not replay a mutating request after an uncertain network failure', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockRejectedValueOnce(new TypeError('Failed to fetch'))

    await expect(apiRequest('/generations/videos', { method: 'POST' })).rejects.toThrow('Failed to fetch')
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })
})
