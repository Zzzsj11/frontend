import { describe, expect, it, vi } from 'vitest'

import {
  createImageTask,
  DEFAULT_IMAGE_WAIT_TIMEOUT_MS,
  fetchPortraitPrompt,
  getTemplateAvatar,
  setTemplateAvatar,
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

describe('template avatar (system character 001 three-view sheet)', () => {
  it('stores and returns the template url used as generation reference', () => {
    setTemplateAvatar('https://tos.test/system/template.png')
    expect(getTemplateAvatar()).toBe('https://tos.test/system/template.png')
    setTemplateAvatar('')
    expect(getTemplateAvatar()).toBe('')
  })
})

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
      prompt: '参照第一张参考图的构图版式。角色描述：青衣少女。画面风格：古风。',
    })

    const task = await createImageTask('', {
      portrait: { description: '青衣少女', style: '古风' },
    })
    expect(task.id).toBe('job-1')
    expect(task.prompt).toContain('参照第一张参考图')
    const body = JSON.parse(String(fetchMock.mock.calls[0][1]?.body))
    expect(body.prompt).toBe('')
    expect(body.portrait).toEqual({ description: '青衣少女', style: '古风' })
  })
})

describe('fetchPortraitPrompt', () => {
  it('requests the registry-assembled prompt from the backend without creating a job', async () => {
    const fetchMock = mockJsonResponse({ prompt: '参照第一张参考图的构图版式。' })

    const prompt = await fetchPortraitPrompt('青衣少女', '古风')
    expect(prompt).toContain('参照第一张参考图')
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
