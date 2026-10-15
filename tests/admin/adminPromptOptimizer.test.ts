import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  createPromptOptimizerTask,
  fetchPromptOptimizerStatus,
  fetchPromptOptimizerTasks,
  queryPromptOptimizerTask,
  uploadPromptOptimizerMedia,
} from '../../src/api/adminPromptOptimizer'
import AdminPromptOptimizerPanel from '../../src/components/AdminPromptOptimizerPanel.vue'
import { generateShotVideo } from '../../src/api/mediaGen'

vi.mock('../../src/api/adminPromptOptimizer', () => ({
  createPromptOptimizerTask: vi.fn(),
  fetchPromptOptimizerStatus: vi.fn(),
  fetchPromptOptimizerTasks: vi.fn(),
  queryPromptOptimizerTask: vi.fn(),
  uploadPromptOptimizerMedia: vi.fn(),
}))

vi.mock('../../src/api/mediaGen', () => ({ generateShotVideo: vi.fn() }))
vi.mock('../../src/generationModels', () => ({
  DEFAULT_IMAGE_MODEL: 'nano-banana-2.1-all-in-one',
  loadGenerationModels: vi.fn(),
  videoRatioChoices: () => ['16:9', '9:16'],
}))

const configuredStatus = {
  providers: {
    gemini: { configured: true, model: 'gemini-3.7-flash', keyTail: '…1234' },
    minimax: { configured: true, model: 'MiniMax-H3', keyTail: '…5678' },
  },
  limits: { images: 9, videos: 3, audios: 3, videoSeconds: 15, audioSeconds: 15 },
  ratios: ['adaptive', '16:9', '9:16'],
  durationRange: [4, 15] as [number, number],
}

describe('admin prompt optimizer panel', () => {
  beforeEach(() => {
    vi.mocked(fetchPromptOptimizerStatus).mockReset().mockResolvedValue(configuredStatus)
    vi.mocked(fetchPromptOptimizerTasks).mockReset().mockResolvedValue({ items: [] })
    vi.mocked(uploadPromptOptimizerMedia).mockReset()
    vi.mocked(createPromptOptimizerTask).mockReset()
    vi.mocked(queryPromptOptimizerTask).mockReset()
  })

  it('uploads mixed media and submits to the selected provider', async () => {
    vi.mocked(uploadPromptOptimizerMedia).mockResolvedValue({
      kind: 'image',
      url: 'https://tos.test/person.jpg',
      thumbnailUrl: 'https://tos.test/person-thumb.jpg',
      name: 'person.jpg',
      mimeType: 'image/jpeg',
      size: 100,
      role: 'reference',
      runningHubFileName: 'rh-person.jpg',
    })
    vi.mocked(createPromptOptimizerTask).mockResolvedValue({
      id: 'task-1',
      provider: 'gemini',
      model: 'gemini-3.7-flash',
      status: 'succeeded',
      inputPrompt: '保持人物身份',
      outputPrompt: 'subject_definitions:\n<Subject 1> test',
      duration: 15,
      ratio: '16:9',
      media: [],
      usage: {},
      error: '',
      createdAt: '2026-08-27T00:00:00Z',
    })

    const wrapper = mount(AdminPromptOptimizerPanel)
    await vi.waitFor(() => expect(fetchPromptOptimizerStatus).toHaveBeenCalled())
    const gemini = wrapper
      .findAll('.provider-switch button')
      .find((item) => item.text().includes('Gemini'))!
    await gemini.trigger('click')
    const file = new File(['image'], 'person.jpg', { type: 'image/jpeg' })
    const input = wrapper.find('input[type="file"]')
    Object.defineProperty(input.element, 'files', { value: [file], configurable: true })
    await input.trigger('change')
    await vi.waitFor(() => expect(uploadPromptOptimizerMedia).toHaveBeenCalledWith(file))
    expect(wrapper.find('.prompt-references').text()).toContain('图片1')
    expect(wrapper.find('.media-order').text()).toBe('1')
    await wrapper.find('.prompt-references button').trigger('click')
    expect((wrapper.find('#optimizer-prompt').element as HTMLTextAreaElement).value).toContain(
      '@图片1',
    )
    await wrapper.find('#optimizer-prompt').setValue('保持人物身份')
    await wrapper.find('.optimize-button').trigger('click')
    await vi.waitFor(() => expect(createPromptOptimizerTask).toHaveBeenCalled())

    expect(createPromptOptimizerTask).toHaveBeenCalledWith(
      expect.objectContaining({ provider: 'gemini', duration: 15, ratio: '16:9' }),
    )
    expect(wrapper.find('.result-output').element.getAttribute('value')).toContain(
      'subject_definitions:',
    )
  })

  it('supports all four H3 generation modes and submits text generation directly', async () => {
    vi.mocked(generateShotVideo).mockResolvedValue({
      coverUrl: '',
      videoUrl: 'https://tos.test/video.mp4',
      duration: 15,
    })
    const wrapper = mount(AdminPromptOptimizerPanel)
    await vi.waitFor(() => expect(fetchPromptOptimizerStatus).toHaveBeenCalled())

    expect(wrapper.findAll('.generation-mode button').map((item) => item.text())).toEqual([
      '文生视频',
      '首帧生成',
      '首尾帧生成',
      '多参考生成',
    ])
    await wrapper.find('#optimizer-prompt').setValue('宫廷舞蹈，镜头缓慢推进')
    await wrapper.findAll('.generation-mode button')[0].trigger('click')
    await wrapper.find('.generate-button').trigger('click')
    await vi.waitFor(() => expect(generateShotVideo).toHaveBeenCalled())
    expect(generateShotVideo).toHaveBeenCalledWith(
      '宫廷舞蹈，镜头缓慢推进',
      undefined,
      [],
      expect.objectContaining({
        h3Mode: 'text',
        videoModel: 'minimax-h3-all-in-one',
        referenceImageUrls: [],
        ratio: '16:9',
      }),
      undefined,
      undefined,
      expect.any(AbortSignal),
    )
    wrapper.unmount()
  })

  it('hides the retired MiniMax optimizer and warns when the platform has no key', async () => {
    vi.mocked(fetchPromptOptimizerStatus).mockResolvedValue({
      ...configuredStatus,
      providers: {
        ...configuredStatus.providers,
        gemini: { configured: false, model: 'gemini-3.8-flash-all-in-one', keyTail: '' },
        minimax: { configured: false, model: '已停用', keyTail: '' },
      },
    })
    const wrapper = mount(AdminPromptOptimizerPanel)
    await vi.waitFor(() =>
      expect(wrapper.find('.provider-switch button.active').text()).toContain('Gemini'),
    )
    expect(wrapper.findAll('.provider-switch button')).toHaveLength(1)
    await vi.waitFor(() => expect(wrapper.text()).toContain('平台服务暂不可用'))
    expect(wrapper.find('.optimize-button').attributes('disabled')).toBeDefined()
  })
})
