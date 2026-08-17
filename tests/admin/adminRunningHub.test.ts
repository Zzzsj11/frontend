import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  fetchRunningHubStatus,
  queryRunningHubTask,
  submitRunningHubTask,
  uploadRunningHubImage,
} from '../../src/api/adminRunningHub'
import AdminRunningHubPanel from '../../src/components/AdminRunningHubPanel.vue'

vi.mock('../../src/api/adminRunningHub', () => ({
  fetchRunningHubStatus: vi.fn(),
  uploadRunningHubImage: vi.fn(),
  submitRunningHubTask: vi.fn(),
  queryRunningHubTask: vi.fn(),
}))

const configuredStatus = {
  configured: true,
  keyTail: '...c817',
  workflowId: '2084514856253874178',
  aspectRatios: ['16:9 (Widescreen)', '9:16 (Portrait)'],
  durationRange: [4, 15] as [number, number],
  megapixelsPresets: [
    { value: 0.4, size: '864×480' },
    { value: 0.9, size: '1280×736' },
    { value: 2.0, size: '1920×1088' },
  ],
  megapixelsDefault: [0.4, 0.9] as [number, number],
}

const buttonByText = (wrapper: ReturnType<typeof mount>, text: string) => {
  const button = wrapper.findAll('button').find((item) => item.text().includes(text))
  expect(button, `button ${text}`).toBeTruthy()
  return button!
}

describe('admin runninghub panel', () => {
  beforeEach(() => {
    vi.mocked(fetchRunningHubStatus).mockReset()
    vi.mocked(uploadRunningHubImage).mockReset()
    vi.mocked(submitRunningHubTask).mockReset()
    vi.mocked(queryRunningHubTask).mockReset()
    localStorage.clear()
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

    await buttonByText(wrapper, '刷新').trigger('click')
    await vi.waitFor(() => expect(queryRunningHubTask).toHaveBeenCalledWith('task-old-9'))
    await new Promise((resolve) => setTimeout(resolve))

    expect(wrapper.find('.rh-table').text()).toContain('SUCCESS')
    expect(wrapper.find('.rh-table a').attributes('href')).toBe('https://cos.test/old.mp4')
    wrapper.unmount()
  })
})
