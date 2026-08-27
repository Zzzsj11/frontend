import { afterEach, describe, expect, it, vi } from 'vitest'
import { createStoryboardLine, dataUrlToBlob, uploadDataUrl } from '../../src/api/domain'

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

  it('normalizes a newly created creative line before immediate H3 generation', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({
          id: 'line-creative',
          source: 'creative',
          shotType: 'creative',
          originalPrompt: '原始描述',
          optimizedPrompt: 'optimized prompt',
          shotPrompt: 'optimized prompt',
          digitalHumanIds: [],
          sceneAssets: [],
          shotAssets: [],
          voiceAssets: [],
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    )

    const line = await createStoryboardLine('task-1', { source: 'creative' })

    expect(line.source).toBe('creative')
    expect(line.manual).toBe(true)
    expect(line.scene).toEqual({ status: 'none', imageUrl: undefined, originalImageUrl: undefined })
    expect(line.shot).toMatchObject({ status: 'none', assets: [] })
    expect(line.voice).toEqual({ status: 'none' })
  })
})
