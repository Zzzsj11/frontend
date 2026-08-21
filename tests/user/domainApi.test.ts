import { afterEach, describe, expect, it, vi } from 'vitest'
import { dataUrlToBlob, uploadDataUrl } from '../../src/api/domain'

describe('digital human reference upload', () => {
  afterEach(() => vi.restoreAllMocks())

  it('decodes base64 and percent-encoded data URLs without fetching data:', () => {
    const jpeg = dataUrlToBlob('data:image/jpeg;base64,aGVsbG8=')
    const svg = dataUrlToBlob('data:image/svg+xml,%3Csvg%3E%3C%2Fsvg%3E')

    expect(jpeg.type).toBe('image/jpeg')
    expect(jpeg.size).toBe(5)
    expect(svg.type).toBe('image/svg+xml')
    expect(svg.size).toBe(11)
  })

  it('sends the decoded image directly to the upload API', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ url: 'https://tos.test/avatar.jpg' }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )

    await uploadDataUrl('data:image/jpeg;base64,aGVsbG8=', 'reference.jpg')

    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/uploads?category=digital-humans')
    expect(init?.body).toBeInstanceOf(FormData)
    expect((init?.body as FormData).get('file')).toBeInstanceOf(Blob)
  })
})
