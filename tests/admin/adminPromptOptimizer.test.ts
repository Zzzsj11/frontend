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
import {
  fetchRunningHubStatus,
  queryRunningHubTask,
  submitRunningHubTask,
  type RunningHubStatus,
} from '../../src/api/adminRunningHub'

vi.mock('../../src/api/adminPromptOptimizer', () => ({
  createPromptOptimizerTask: vi.fn(),
  fetchPromptOptimizerStatus: vi.fn(),
  fetchPromptOptimizerTasks: vi.fn(),
  queryPromptOptimizerTask: vi.fn(),
  uploadPromptOptimizerMedia: vi.fn(),
}))

vi.mock('../../src/api/adminRunningHub', () => ({
  fetchRunningHubStatus: vi.fn(),
  queryRunningHubTask: vi.fn(),
  submitRunningHubTask: vi.fn(),
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

const runningHubStatus: RunningHubStatus = {
  configured: true,
  keyTail: '…c817',
  workflowId: 'workflow-1',
  modes: ['reference', 'text', 'first_frame', 'first_last'],
  aspectRatios: ['16:9 (Widescreen)'],
  firstFrameAspectRatios: ['16:9 (Widescreen)'],
  textAspectRatios: ['16:9 (Widescreen)'],
  durationRange: [4, 15] as [number, number],
  megapixelsPresets: [{ value: 0.9, size: '1280×736' }],
  megapixelsDefault: [0.4, 0.9] as [number, number],
  textMegapixelsDefault: 0.9,
  firstFrameMegapixelsDefault: 0.9,
}

describe('admin prompt optimizer panel', () => {
  beforeEach(() => {
    vi.mocked(fetchPromptOptimizerStatus).mockReset().mockResolvedValue(configuredStatus)
    vi.mocked(fetchPromptOptimizerTasks).mockReset().mockResolvedValue({ items: [] })
    vi.mocked(uploadPromptOptimizerMedia).mockReset()
    vi.mocked(createPromptOptimizerTask).mockReset()
    vi.mocked(queryPromptOptimizerTask).mockReset()
    vi.mocked(fetchRunningHubStatus).mockReset().mockResolvedValue(runningHubStatus)
    vi.mocked(queryRunningHubTask).mockReset()
    vi.mocked(submitRunningHubTask).mockReset()
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
    vi.mocked(submitRunningHubTask).mockResolvedValue({ taskId: 'h3-task-1', status: 'QUEUED' })
    const wrapper = mount(AdminPromptOptimizerPanel)
    await vi.waitFor(() => expect(fetchRunningHubStatus).toHaveBeenCalled())

    expect(wrapper.findAll('.generation-mode button').map((item) => item.text())).toEqual([
      '文生视频',
      '首帧生成',
      '首尾帧生成',
      '多参考生成',
    ])
    await wrapper.find('#optimizer-prompt').setValue('宫廷舞蹈，镜头缓慢推进')
    await wrapper.findAll('.generation-mode button')[0].trigger('click')
    await wrapper.find('.generate-button').trigger('click')
    await vi.waitFor(() => expect(submitRunningHubTask).toHaveBeenCalled())
    expect(submitRunningHubTask).toHaveBeenCalledWith(
      expect.objectContaining({
        mode: 'text',
        prompt: '宫廷舞蹈，镜头缓慢推进',
        images: [],
        aspectRatio: '16:9 (Widescreen)',
      }),
    )
    wrapper.unmount()
  })

  it('shows configuration warning and disables optimization when a provider has no key', async () => {
    vi.mocked(fetchPromptOptimizerStatus).mockResolvedValue({
      ...configuredStatus,
      providers: {
        ...configuredStatus.providers,
        minimax: { configured: false, model: 'MiniMax-H3', keyTail: '' },
      },
    })
    const wrapper = mount(AdminPromptOptimizerPanel)
    await vi.waitFor(() =>
      expect(wrapper.find('.provider-switch button.active').text()).toContain('Gemini'),
    )
    const minimax = wrapper
      .findAll('.provider-switch button')
      .find((item) => item.text().includes('MiniMax'))!
    await minimax.trigger('click')
    await wrapper.vm.$nextTick()
    expect(wrapper.text()).toContain('未配置后端密钥')
    expect(wrapper.find('.optimize-button').attributes('disabled')).toBeDefined()
  })
})
