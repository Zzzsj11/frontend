import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useGenerationPreferences } from '../../src/stores/generationPreferences'
import { apiRequest } from '../../src/api/client'
vi.mock('../../src/api/client', () => ({ apiRequest: vi.fn() }))
beforeEach(() => {
  setActivePinia(createPinia())
  vi.mocked(apiRequest).mockReset()
})
describe('user generation preferences', () => {
  it('persists automatic routing as null and only updates after successful save', async () => {
    const store = useGenerationPreferences()
    const selection = { model: 'nano-banana-2.1-all-in-one', channel: null }
    vi.mocked(apiRequest).mockResolvedValueOnce({ image: selection })
    await store.save('image', selection)
    expect(apiRequest).toHaveBeenCalledWith('/generation-preferences/image', {
      method: 'PUT',
      body: JSON.stringify(selection),
    })
    vi.mocked(apiRequest).mockRejectedValueOnce(new Error('unavailable'))
    await expect(store.save('image', { ...selection, channel: 'gone' })).rejects.toThrow()
    expect(store.selections.image).toEqual(selection)
    expect(store.saving).toBe(false)
  })
  it('does not leak a previous account response into a new account', async () => {
    const store = useGenerationPreferences()
    let resolve!: (value: unknown) => void
    vi.mocked(apiRequest).mockImplementationOnce(
      () =>
        new Promise((done) => {
          resolve = done
        }) as never,
    )
    const old = store.load('old')
    vi.mocked(apiRequest).mockResolvedValueOnce({})
    await store.load('new')
    resolve({ video: { model: 'old-private-choice', channel: 'old-channel' } })
    await old
    expect(store.ownerId).toBe('new')
    expect(store.selections).toEqual({})
  })
})
