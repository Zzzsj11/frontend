import { describe, expect, it, vi } from 'vitest'

import {
  createImageTask,
  DEFAULT_IMAGE_WAIT_TIMEOUT_MS,
  fetchPortraitPrompt,
} from '../../src/api/imageGen'

function mockJsonResponse(body: unknown) {
  return vi.spyOn(globalThis, 'fetch').mockImplementation(
    async () =>
      new Response(JSON.stringify(body), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
  )
}

describe('createImageTask', () => {
  it('serializes reference images and the digital_human purpose into the request body', async () => {
    const fetchMock = mockJsonResponse({ id: 'job-1', status: 'queued', progress: 0 })

    const task = await createImageTask('prompt', { image: ['a.png', 'b.png'] })
    expect(task.id).toBe('job-1')
    const body = JSON.parse(String(fetchMock.mock.calls[0][1]?.body))
    expect(body.images).toEqual(['a.png', 'b.png'])
    expect(body.purpose).toBe('digital_human')
    expect(body.size).toBe('1024x1024')
    expect(body).not.toHaveProperty('portrait')
  })

  it('normalizes a single reference image into an array and omits images when absent', async () => {
    const fetchMock = mockJsonResponse({ id: 'job-1', status: 'queued', progress: 0 })

    await createImageTask('prompt', { image: 'only.png' })
    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body)).images).toEqual(['only.png'])

    await createImageTask('prompt')
    expect(JSON.parse(String(fetchMock.mock.calls[1][1]?.body))).not.toHaveProperty('images')
  })

  it('passes portrait params through and surfaces the backend-assembled prompt', async () => {
    const fetchMock = mockJsonResponse({
      id: 'job-1',
      status: 'queued',
      progress: 0,
      prompt: '生成单张正面头肩大头照。角色描述：青衣少女。',
    })

    const task = await createImageTask('', {
      portrait: { description: '青衣少女', style: '古风' },
    })
    expect(task.id).toBe('job-1')
    expect(task.prompt).toContain('单张正面头肩大头照')
    const body = JSON.parse(String(fetchMock.mock.calls[0][1]?.body))
    expect(body.prompt).toBe('')
    expect(body.portrait).toEqual({ description: '青衣少女', style: '古风' })
  })

  it('passes GPT Image 2.5 quality values through unchanged', async () => {
    const fetchMock = mockJsonResponse({ id: 'job-25', status: 'queued', progress: 0 })

    await createImageTask('精细生成', { quality: 'max' })

    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body)).quality).toBe('max')
  })
})

describe('fetchPortraitPrompt', () => {
  it('requests the registry-assembled prompt from the backend without creating a job', async () => {
    const fetchMock = mockJsonResponse({ prompt: '生成单张正面头肩大头照。' })

    const prompt = await fetchPortraitPrompt('青衣少女', '古风')
    expect(prompt).toContain('单张正面头肩大头照')
    const [url, init] = fetchMock.mock.calls[0]
    expect(String(url)).toContain('/generations/images/portrait-prompt')
    expect(JSON.parse(String(init?.body))).toEqual({ description: '青衣少女', style: '古风' })
  })
})

describe('image generation timeout contract', () => {
  it('waits beyond the backend ten-minute provider deadline', () => {
    expect(DEFAULT_IMAGE_WAIT_TIMEOUT_MS).toBe(660_000)
  })
})
