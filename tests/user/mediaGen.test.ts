import { imageRecoveryActions } from '../../src/utils/imageGenerationRecovery'
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
    expect(JSON.parse(String(fetchMock.mock.calls[0]?.[1]?.body)).size).toBe('9:16')
    expect(JSON.parse(String(fetchMock.mock.calls[0]?.[1]?.body)).resolution).toBe('1K')
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

  it('defaults H3 generation with available images to automatic mode', async () => {
    vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(jsonResponse({ id: 'job-ref2va', status: 'queued', progress: 0 }))
      .mockResolvedValueOnce(
        jsonResponse({
          id: 'job-ref2va',
          status: 'succeeded',
          progress: 100,
          result: { videoUrl: '/media/videos/ref2va.mp4', duration: 5 },
        }),
      )

    await generateShotVideo('reference generation', '/media/scene.jpg', ['/media/human.jpg'], {
      resolution: '720p',
      duration: 5,
      ratio: '16:9',
      imageModel: DEFAULT_IMAGE_MODEL,
      videoModel: 'minimax-h3',
    })

    const body = JSON.parse(String(vi.mocked(fetch).mock.calls[0]?.[1]?.body))
    expect(body.h3_mode).toBe('auto')
    expect(body.image_urls).toEqual(['/media/scene.jpg', '/media/human.jpg'])
  })

  it.each(['minimax-h3', 'minimax-h3-runninghub'])(
    'submits %s without references in automatic text mode',
    async (videoModel) => {
      const fetchMock = vi
        .spyOn(globalThis, 'fetch')
        .mockResolvedValueOnce(jsonResponse({ id: 'job-t2va', status: 'queued', progress: 0 }))
        .mockResolvedValueOnce(
          jsonResponse({
            id: 'job-t2va',
            status: 'succeeded',
            progress: 100,
            result: { videoUrl: '/media/videos/t2va.mp4', duration: 5 },
          }),
        )

      await generateShotVideo('text generation', undefined, [], {
        resolution: '720p',
        duration: 5,
        ratio: '16:9',
        imageModel: DEFAULT_IMAGE_MODEL,
        videoModel,
        h3Mode: 'reference',
      })

      const body = JSON.parse(String(fetchMock.mock.calls[0]?.[1]?.body))
      expect(body.h3_mode).toBe('auto')
      expect(body.image_urls).toEqual([])
      expect(body.video_urls).toEqual([])
    },
  )

  it('surfaces a failed generation reason', async () => {
    vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(jsonResponse({ id: 'job-failed', status: 'queued', progress: 0 }))
      .mockResolvedValueOnce(
        jsonResponse({ id: 'job-failed', status: 'failed', progress: 5, error: 'provider denied' }),
      )

    const pending = expect(generateScene('test')).rejects.toThrow('provider denied')
    await vi.waitFor(() => expect(imageRecoveryActions.get('job-failed')?.label).toBe('重新生成'))
    imageRecoveryActions.get('job-failed')?.dismiss?.()
    await pending
  })
})

it('refreshes an overdue image using the original job ID', async () => {
  const { waitForRecoverableImage } = await import('../../src/utils/imageGenerationRecovery')
  const fetchMock = vi
    .spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(jsonResponse([{ id: 'slow-image', status: 'running' }]))
    .mockResolvedValueOnce(
      jsonResponse([{ id: 'slow-image', status: 'succeeded', result: { urls: ['/done.png'] } }]),
    )
  const pending = waitForRecoverableImage('slow-image', (job) => job.result, { timeoutMs: 1 })
  await vi.waitFor(() => expect(imageRecoveryActions.get('slow-image')?.label).toBe('刷新状态'))
  imageRecoveryActions.get('slow-image')?.run()
  await expect(pending).resolves.toEqual({ urls: ['/done.png'] })
  expect(
    fetchMock.mock.calls.slice(0, 2).map(([, request]) => JSON.parse(String(request?.body))),
  ).toEqual([{ ids: ['slow-image'] }, { ids: ['slow-image'] }])
})

it('creates a second image job only after an explicit retry of a confirmed failure', async () => {
  const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, request) => {
    if (String(url).endsWith('/generations/observed')) return jsonResponse({ ok: true })
    if (String(url).endsWith('/generations/images'))
      return jsonResponse({
        id: submissions().length === 1 ? 'first-image' : 'second-image',
        status: 'queued',
      })
    const id = JSON.parse(String(request?.body)).ids[0]
    return jsonResponse([
      id === 'first-image'
        ? { id, status: 'failed', error: '平台明确拒绝' }
        : { id, status: 'succeeded', result: { urls: ['/done.png'] } },
    ])
  })
  const submissions = () =>
    fetchMock.mock.calls.filter(([url]) => String(url).endsWith('/generations/images'))
  const pending = generateScene('retryable prompt')
  await vi.waitFor(() => expect(imageRecoveryActions.get('first-image')?.label).toBe('重新生成'))
  expect(submissions()).toHaveLength(1)
  imageRecoveryActions.get('first-image')?.run()
  await expect(pending).resolves.toMatchObject({ imageUrl: '/done.png' })
  expect(submissions()).toHaveLength(2)
  expect(submissions()[1][1]?.body).toBe(submissions()[0][1]?.body)
})
