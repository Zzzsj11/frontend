import { describe, expect, it, vi } from 'vitest'

import {
  buildPortraitPrompt,
  createImageTask,
  getTemplateAvatar,
  setTemplateAvatar,
} from '../src/api/imageGen'

describe('buildPortraitPrompt', () => {
  it('anchors the prompt to the first reference image with description and style', () => {
    const prompt = buildPortraitPrompt('青衣少女，及腰长发', '古风')
    expect(prompt).toContain('参照第一张参考图的构图版式')
    expect(prompt).toContain('角色描述：青衣少女，及腰长发')
    expect(prompt).toContain('画面风格：古风')
  })

  it('omits empty parts instead of leaving dangling labels', () => {
    const prompt = buildPortraitPrompt('', '')
    expect(prompt).toContain('参照第一张参考图')
    expect(prompt).not.toContain('角色描述')
    expect(prompt).not.toContain('画面风格')
  })
})

describe('template avatar (system character 001 three-view sheet)', () => {
  it('stores and returns the template url used as generation reference', () => {
    setTemplateAvatar('https://tos.test/system/template.png')
    expect(getTemplateAvatar()).toBe('https://tos.test/system/template.png')
    // 复位，避免污染其它测试文件（模块级单例）
    setTemplateAvatar('')
    expect(getTemplateAvatar()).toBe('')
  })
})

describe('createImageTask', () => {
  it('serializes reference images and the digital_human purpose into the request body', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(
      async () =>
        new Response(JSON.stringify({ id: 'job-1', status: 'queued', progress: 0 }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
    )

    const taskId = await createImageTask('prompt', { image: ['a.png', 'b.png'] })
    expect(taskId).toBe('job-1')
    const body = JSON.parse(String(fetchMock.mock.calls[0][1]?.body))
    expect(body.images).toEqual(['a.png', 'b.png'])
    expect(body.purpose).toBe('digital_human')
    expect(body.size).toBe('1024x1024')
  })

  it('normalizes a single reference image into an array and omits images when absent', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(
      async () =>
        new Response(JSON.stringify({ id: 'job-1', status: 'queued', progress: 0 }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
    )

    await createImageTask('prompt', { image: 'only.png' })
    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body)).images).toEqual(['only.png'])

    await createImageTask('prompt')
    expect(JSON.parse(String(fetchMock.mock.calls[1][1]?.body))).not.toHaveProperty('images')
  })
})
