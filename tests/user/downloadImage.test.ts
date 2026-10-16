import { afterEach, describe, expect, it, vi } from 'vitest'
import { apiRequest } from '../../src/api/client'
vi.mock('../../src/api/client', () => ({ apiRequest: vi.fn() }))
import { downloadImage } from '../../src/api/downloadImage'

afterEach(() => vi.restoreAllMocks())
describe('original image downloads', () => {
  it('downloads TOS media through attachment headers without a CORS fetch', async () => {
    const fetch = vi.spyOn(globalThis, 'fetch').mockRejectedValue(new Error('CORS blocked'))
    let href = ''
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (
      this: HTMLAnchorElement,
    ) {
      href = this.href
    })
    vi.mocked(apiRequest).mockResolvedValue({
      url: 'https://media.tos-cn-beijing.volces.com/scene.webp?signed=yes',
    })
    await downloadImage(
      'https://media.tos-cn-beijing.volces.com/users/me/scene.webp',
      '场景 / 原图',
    )
    expect(fetch).not.toHaveBeenCalled()
    const url = new URL(href)
    expect(url.hostname).toBe('media.tos-cn-beijing.volces.com')
    expect(url.searchParams.get('signed')).toBe('yes')
    expect(apiRequest).toHaveBeenCalledWith(
      expect.stringContaining('/media/image-download?'),
      {},
      true,
      [403, 422, 503],
    )
  })
})
