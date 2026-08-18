import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  fetchRunningHubComparisonSources,
  fetchRunningHubStatus,
  fetchRunningHubPresets,
  queryRunningHubTask,
  submitRunningHubComparisonWithRefs,
  submitRunningHubTask,
  uploadRunningHubImage,
} from '../../src/api/adminRunningHub'
import AdminRunningHubPanel from '../../src/components/AdminRunningHubPanel.vue'

vi.mock('../../src/api/adminRunningHub', () => ({
  fetchRunningHubComparisonSources: vi.fn(),
  fetchRunningHubStatus: vi.fn(),
  fetchRunningHubPresets: vi.fn(),
  uploadRunningHubImage: vi.fn(),
  submitRunningHubTask: vi.fn(),
  queryRunningHubTask: vi.fn(),
  submitRunningHubComparisonWithRefs: vi.fn(),
}))

const configuredStatus = {
  configured: true,
  keyTail: '...c817',
  workflowId: '2084514856253874178',
  modes: ['reference', 'text', 'first_frame'] as Array<'reference' | 'text' | 'first_frame'>,
  aspectRatios: ['16:9 (Widescreen)', '9:16 (Portrait)'],
  firstFrameAspectRatios: ['16:9 (Widescreen)', '3:4 (Portrait Standard)'],
  textAspectRatios: ['16:9 (Widescreen)', '9:16 (Portrait Widescreen)'],
  durationRange: [4, 15] as [number, number],
  megapixelsPresets: [
    { value: 0.4, size: '864×480' },
    { value: 0.9, size: '1280×736' },
    { value: 2.0, size: '1920×1088' },
  ],
  megapixelsDefault: [0.4, 0.9] as [number, number],
  textMegapixelsDefault: 0.9,
  firstFrameMegapixelsDefault: 0.9,
}

const buttonByText = (wrapper: ReturnType<typeof mount>, text: string) => {
  const button = wrapper.findAll('button').find((item) => item.text().includes(text))
  expect(button, `button ${text}`).toBeTruthy()
  return button!
}

describe('admin runninghub panel', () => {
  beforeEach(() => {
    vi.mocked(fetchRunningHubComparisonSources).mockReset()
    vi.mocked(fetchRunningHubComparisonSources).mockResolvedValue({ items: [] })
    vi.mocked(fetchRunningHubStatus).mockReset()
    vi.mocked(fetchRunningHubPresets).mockReset()
    vi.mocked(fetchRunningHubPresets).mockResolvedValue({ items: [] })
    vi.mocked(uploadRunningHubImage).mockReset()
    vi.mocked(submitRunningHubTask).mockReset()
    vi.mocked(queryRunningHubTask).mockReset()
    vi.mocked(submitRunningHubComparisonWithRefs).mockReset()
    localStorage.clear()
  })

  it('selects a generated Seedance shot and submits an H3 comparison', async () => {
    vi.mocked(fetchRunningHubStatus).mockResolvedValue(configuredStatus)
    vi.mocked(fetchRunningHubComparisonSources).mockResolvedValue({
      items: [
        {
          lineId: 'line-1',
          lineOrder: 2,
          shotType: 'character',
          prompt: '人物沿着海边缓慢行走',
          coverUrl: 'https://tos.test/cover.jpg',
          seedanceUrl: 'https://tos.test/seedance.mp4',
          duration: 8,
          username: 'dev01',
          userId: 'user-1',
          projectId: 'project-1',
          projectName: '测试项目',
          taskId: 'story-task-1',
          taskTitle: '通用分镜',
          referenceCandidates: [
            { id: 'ref-cover', label: '首帧', url: 'https://tos.test/cover.jpg', kind: 'cover' },
            { id: 'ref-char', label: '人物A', url: 'https://tos.test/char.jpg', kind: 'character' },
          ],
        },
      ],
    })
    vi.mocked(submitRunningHubComparisonWithRefs).mockResolvedValue({
      id: 'comparison-1',
      name: '对比 · dev01 · 通用分镜 · 镜头 3 · reference',
      mode: 'reference',
      comparisonMode: 'reference',
      prompt: '请严格参考下列图片并保持人物、场景和镜头风格一致：\n<Picture 1> 首帧\n<Picture 2> 人物A\n\n人物沿着海边缓慢行走',
      duration: 8,
      aspectRatio: '16:9 (Widescreen)',
      inputMedia: [
        {
          type: 'image',
          url: 'https://tos.test/cover.jpg',
          name: 'Seedance 首帧',
          role: 'comparison_cover',
        },
        {
          type: 'image',
          url: 'https://tos.test/char.jpg',
          name: '人物A',
          role: 'cast_reference',
        },
        {
          type: 'video',
          url: 'https://tos.test/seedance.mp4',
          role: 'seedance_source',
          username: 'dev01',
          projectName: '测试项目',
          taskTitle: '通用分镜',
          shotType: 'character',
        },
      ],
      outputMedia: [],
      taskId: null,
      taskStatus: 'QUEUED',
      usage: {},
      createdAt: '2026-08-18T00:00:00Z',
    })

    const wrapper = mount(AdminRunningHubPanel)
    await vi.waitFor(() => expect(wrapper.text()).toContain('H3 × Seedance 固定对比'))
    expect(wrapper.text()).toContain('dev01')
    expect(wrapper.text()).toContain('镜头 3')

    await buttonByText(wrapper, '使用 H3 生成对比').trigger('click')
    await vi.waitFor(() =>
      expect(submitRunningHubComparisonWithRefs).toHaveBeenCalledWith({
        lineId: 'line-1',
        referenceUrls: ['https://tos.test/cover.jpg', 'https://tos.test/char.jpg'],
        comparisonMode: 'multi_reference',
      }),
    )
    expect(wrapper.text()).toContain('Seedance 2.0 原视频')
    expect(wrapper.text()).toContain('MiniMax H3 生成视频')
    wrapper.unmount()
  })

  it('shows setup hint and disables submit when api key is not configured', async () => {
    vi.mocked(fetchRunningHubStatus).mockResolvedValue({
      ...configuredStatus,
      configured: false,
      keyTail: '',
    })
    const wrapper = mount(AdminRunningHubPanel)
    await vi.waitFor(() => expect(wrapper.text()).toContain('RUNNINGHUB_API_KEY'))
    expect(wrapper.find('.submit-btn').attributes('disabled')).toBeDefined()
    wrapper.unmount()
  })

  it('submits with filled template and polls until success with video result', async () => {
    vi.useFakeTimers()
    try {
      vi.mocked(fetchRunningHubStatus).mockResolvedValue(configuredStatus)
      vi.mocked(submitRunningHubTask).mockResolvedValue({ taskId: 'task-001', status: 'RUNNING' })
      vi.mocked(queryRunningHubTask).mockResolvedValue({
        taskId: 'task-001',
        status: 'SUCCESS',
        results: [
          { url: 'https://cos.test/out.mp4', nodeId: '386', outputType: 'mp4', text: null },
        ],
        usage: { consumeCoins: '90', taskCostTime: '446' },
      })
      const wrapper = mount(AdminRunningHubPanel)
      await vi.advanceTimersByTimeAsync(0)
      expect(wrapper.text()).toContain('Key 已配置 ...c817')

      await buttonByText(wrapper, '填入示例模板').trigger('click')
      expect(wrapper.find('.prompt-input').element).toHaveProperty(
        'value',
        expect.stringContaining('subject_definitions:'),
      )

      await wrapper.find('.slot-input').setValue('openapi/ref1.png')
      const submitButton = wrapper.find('.submit-btn')
      expect(submitButton.attributes('disabled')).toBeUndefined()
      await submitButton.trigger('click')
      await vi.advanceTimersByTimeAsync(0)

      expect(submitRunningHubTask).toHaveBeenCalledWith({
        mode: 'reference',
        prompt: expect.stringContaining('subject_definitions:'),
        duration: 8,
        aspectRatio: '16:9 (Widescreen)',
        images: ['openapi/ref1.png'],
        seed: null,
        stage1Megapixels: 0.4,
        stage2Megapixels: 0.9,
      })
      expect(wrapper.text()).toContain('task-001')
      expect(wrapper.text()).toContain('RUNNING')

      await vi.advanceTimersByTimeAsync(5000)
      expect(queryRunningHubTask).toHaveBeenCalledWith('task-001')
      expect(wrapper.find('video').attributes('src')).toBe('https://cos.test/out.mp4')
      expect(wrapper.text()).toContain('90 RH 币')

      const saved = JSON.parse(localStorage.getItem('runninghub-test-history') ?? '[]')
      expect(saved[0]).toMatchObject({
        taskId: 'task-001',
        status: 'SUCCESS',
        videoUrl: 'https://cos.test/out.mp4',
      })
      wrapper.unmount()
    } finally {
      vi.useRealTimers()
    }
  })

  it('submits text-to-video without requiring a reference image', async () => {
    vi.mocked(fetchRunningHubStatus).mockResolvedValue(configuredStatus)
    vi.mocked(submitRunningHubTask).mockResolvedValue({ taskId: 'task-text-1', status: 'QUEUED' })
    const wrapper = mount(AdminRunningHubPanel)
    await vi.waitFor(() => expect(wrapper.text()).toContain('Key 已配置'))

    await buttonByText(wrapper, '纯文本生成').trigger('click')
    await wrapper.vm.$nextTick()
    await buttonByText(wrapper, '填入示例模板').trigger('click')
    expect(wrapper.findAll('.slot-input')).toHaveLength(0)
    expect(wrapper.find('.submit-btn').attributes('disabled')).toBeUndefined()
    await wrapper.find('.submit-btn').trigger('click')

    await vi.waitFor(() =>
      expect(submitRunningHubTask).toHaveBeenCalledWith({
        mode: 'text',
        prompt: expect.stringContaining('small red fox'),
        duration: 8,
        aspectRatio: '16:9 (Widescreen)',
        images: [],
        seed: null,
        textMegapixels: 0.9,
      }),
    )
    wrapper.unmount()
  })

  it('submits first-frame video with exactly one image', async () => {
    vi.mocked(fetchRunningHubStatus).mockResolvedValue(configuredStatus)
    vi.mocked(submitRunningHubTask).mockResolvedValue({ taskId: 'task-first-1', status: 'RUNNING' })
    const wrapper = mount(AdminRunningHubPanel)
    await vi.waitFor(() => expect(wrapper.text()).toContain('Key 已配置'))

    await wrapper.findAll('.slot-input')[1].setValue('openapi/stale.png')
    await buttonByText(wrapper, '首帧生成').trigger('click')
    await buttonByText(wrapper, '填入示例模板').trigger('click')
    await wrapper.find('.slot-input').setValue('openapi/first.png')
    await wrapper.find('.submit-btn').trigger('click')

    await vi.waitFor(() =>
      expect(submitRunningHubTask).toHaveBeenCalledWith({
        mode: 'first_frame',
        prompt: expect.stringContaining('0.00 seconds'),
        duration: 8,
        aspectRatio: '16:9 (Widescreen)',
        images: ['openapi/first.png'],
        seed: null,
        firstFrameMegapixels: 0.9,
      }),
    )
    wrapper.unmount()
  })

  it('uploads a local image and fills the slot with returned fileName', async () => {
    vi.mocked(fetchRunningHubStatus).mockResolvedValue(configuredStatus)
    vi.mocked(uploadRunningHubImage).mockResolvedValue({
      fileName: 'openapi/abc.png',
      downloadUrl: 'https://cos.test/in.png',
      size: '1024',
    })
    const wrapper = mount(AdminRunningHubPanel)
    await vi.waitFor(() => expect(fetchRunningHubStatus).toHaveBeenCalled())
    await new Promise((resolve) => setTimeout(resolve))

    const file = new File(['png-bytes'], 'ref.png', { type: 'image/png' })
    const input = wrapper.find('input[type="file"]')
    Object.defineProperty(input.element, 'files', { value: [file], configurable: true })
    await input.trigger('change')
    await vi.waitFor(() => expect(uploadRunningHubImage).toHaveBeenCalledWith(file))
    await new Promise((resolve) => setTimeout(resolve))

    expect((wrapper.find('.slot-input').element as HTMLInputElement).value).toBe('openapi/abc.png')
    expect(wrapper.find('.slot-thumb').attributes('src')).toBe('https://cos.test/in.png')
    wrapper.unmount()
  })

  it('renders stored history and refreshes entry status', async () => {
    localStorage.setItem(
      'runninghub-test-history',
      JSON.stringify([
        {
          taskId: 'task-old-9',
          time: '2026/8/16 10:00:00',
          duration: 8,
          aspectRatio: '16:9 (Widescreen)',
          imageCount: 1,
          status: 'RUNNING',
          videoUrl: '',
        },
      ]),
    )
    vi.mocked(fetchRunningHubStatus).mockResolvedValue(configuredStatus)
    vi.mocked(queryRunningHubTask).mockResolvedValue({
      taskId: 'task-old-9',
      status: 'SUCCESS',
      results: [{ url: 'https://cos.test/old.mp4', nodeId: '386', outputType: 'mp4', text: null }],
      usage: null,
    })
    const wrapper = mount(AdminRunningHubPanel)
    await vi.waitFor(() => expect(wrapper.text()).toContain('task-old-9'.slice(-8)))

    await wrapper.get('.rh-table .ghost-btn').trigger('click')
    await vi.waitFor(() => expect(queryRunningHubTask).toHaveBeenCalledWith('task-old-9'))
    await new Promise((resolve) => setTimeout(resolve))

    expect(wrapper.find('.rh-table').text()).toContain('SUCCESS')
    expect(wrapper.find('.rh-table a').attributes('href')).toBe('https://cos.test/old.mp4')
    wrapper.unmount()
  })
})
