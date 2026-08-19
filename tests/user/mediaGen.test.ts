import { describe, expect, it, vi } from 'vitest'
import { generateScene, generateShotVideo } from '../../src/api/mediaGen'
import { DEFAULT_IMAGE_MODEL, DEFAULT_VIDEO_MODEL } from '../../src/generationModels'

const jsonResponse = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })

describe('media generation API client', () => {
  it('creates and polls a scene image job', async () => {
    const fetchMock = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(jsonResponse({ id: 'job-image', status: 'queued', progress: 0 }))
      .mockResolvedValueOnce(
        jsonResponse({
          id: 'job-image',
          status: 'succeeded',
          progress: 100,
          result: { urls: ['/media/images/scene.png'] },
        }),
      )

    await expect(
      generateScene('sunlit room', undefined, undefined, '9:16', DEFAULT_IMAGE_MODEL),
    ).resolves.toEqual({
      imageUrl: '/media/images/scene.png',
    })
    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      '/api/generations/images',
      expect.objectContaining({ method: 'POST' }),
    )
    expect(JSON.parse(String(fetchMock.mock.calls[0]?.[1]?.body)).size).toBe('1024x1536')
    expect(JSON.parse(String(fetchMock.mock.calls[0]?.[1]?.body)).quality).toBe('medium')
    expect(JSON.parse(String(fetchMock.mock.calls[0]?.[1]?.body)).model).toBe(DEFAULT_IMAGE_MODEL)
  })

  it('passes the scene image into video generation', async () => {
    vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(jsonResponse({ id: 'job-video', status: 'queued', progress: 0 }))
      .mockResolvedValueOnce(
        jsonResponse({
          id: 'job-video',
          status: 'succeeded',
          progress: 100,
          result: { videoUrl: '/media/videos/shot.mp4', duration: 5 },
        }),
      )

    const result = await generateShotVideo('slow push in', '/media/images/scene.png', [], {
      resolution: '1080p',
      duration: 5,
      ratio: '16:9',
      imageModel: DEFAULT_IMAGE_MODEL,
      videoModel: DEFAULT_VIDEO_MODEL,
      generateAudio: true,
      watermark: true,
    })
    expect(result).toEqual({
      coverUrl: '/media/images/scene.png',
      videoUrl: '/media/videos/shot.mp4',
      duration: 5,
    })

    const body = JSON.parse(String(vi.mocked(fetch).mock.calls[0]?.[1]?.body))
    expect(body.image_urls).toEqual(['/media/images/scene.png'])
    expect(body.resolution).toBe('1080p')
    expect(body.model).toBe(DEFAULT_VIDEO_MODEL)
    expect(body.generate_audio).toBe(true)
    expect(body.watermark).toBe(true)
  })

  it('submits H3 FL2VA with exactly the selected first and last frames', async () => {
    vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(jsonResponse({ id: 'job-fl2va', status: 'queued', progress: 0 }))
      .mockResolvedValueOnce(
        jsonResponse({
          id: 'job-fl2va',
          status: 'succeeded',
          progress: 100,
          result: { videoUrl: '/media/videos/fl2va.mp4', duration: 8 },
        }),
      )

    await generateShotVideo('continuous transition', '/media/current-scene.jpg', [], {
      resolution: '720p',
      duration: 8,
      ratio: '16:9',
      imageModel: DEFAULT_IMAGE_MODEL,
      videoModel: 'minimax-h3-runninghub',
      h3Mode: 'first_last',
      h3FirstFrameUrl: '/media/first.jpg',
      h3LastFrameUrl: '/media/last.jpg',
      referenceVideoUrls: ['/media/ignored.mp4'],
    })

    const body = JSON.parse(String(vi.mocked(fetch).mock.calls[0]?.[1]?.body))
    expect(body.h3_mode).toBe('first_last')
    expect(body.image_urls).toEqual(['/media/first.jpg', '/media/last.jpg'])
    expect(body.video_urls).toEqual([])
    expect(body.audio_urls).toEqual([])
  })

  it('surfaces a failed generation reason', async () => {
    vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(jsonResponse({ id: 'job-failed', status: 'queued', progress: 0 }))
      .mockResolvedValueOnce(
        jsonResponse({ id: 'job-failed', status: 'failed', progress: 5, error: 'provider denied' }),
      )

    await expect(generateScene('test')).rejects.toThrow('provider denied')
  })
})
