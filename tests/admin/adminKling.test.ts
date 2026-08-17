import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { fetchKlingStatus, queryKlingTask, submitKlingTask } from '../../src/api/adminKling'
import AdminKlingPanel from '../../src/components/AdminKlingPanel.vue'

vi.mock('../../src/api/adminKling', () => ({
  fetchKlingStatus: vi.fn(),
  submitKlingTask: vi.fn(),
  queryKlingTask: vi.fn(),
}))

const configuredStatus = {
  configured: true,
  keyTail: '...9abc',
  baseUrl: 'https://api-aigc.fzyinghe.com',
  model: 'kling-v3-omni',
  modes: ['std', 'pro', '4k'],
  aspectRatios: ['16:9', '9:16', '1:1'],
  imageTypes: ['first_frame', 'end_frame', 'reference'],
  durationRange: [3, 15] as [number, number],
}

const buttonByText = (wrapper: ReturnType<typeof mount>, text: string) => {
  const button = wrapper.findAll('button').find((item) => item.text().includes(text))
  expect(button, `button ${text}`).toBeTruthy()
  return button!
}

const flush = () => new Promise((resolve) => setTimeout(resolve))

describe('admin kling panel', () => {
  beforeEach(() => {
    vi.mocked(fetchKlingStatus).mockReset()
    vi.mocked(submitKlingTask).mockReset()
    vi.mocked(queryKlingTask).mockReset()
    localStorage.clear()
  })

  it('shows setup hint and disables submit when api key is not configured', async () => {
    vi.mocked(fetchKlingStatus).mockResolvedValue({
      ...configuredStatus,
      configured: false,
      keyTail: '',
    })
    const wrapper = mount(AdminKlingPanel)
    await vi.waitFor(() => expect(wrapper.text()).toContain('KLING_API_KEY'))
    expect(wrapper.find('.submit-btn').attributes('disabled')).toBeDefined()
    wrapper.unmount()
  })

  it('submits a text-to-video task and polls until succeed with video result', async () => {
    vi.useFakeTimers()
    try {
      vi.mocked(fetchKlingStatus).mockResolvedValue(configuredStatus)
      vi.mocked(submitKlingTask).mockResolvedValue({ taskId: 'k-task-1', status: 'submitted' })
      vi.mocked(queryKlingTask).mockResolvedValue({
        task_id: 'k-task-1',
        task_status: 'succeed',
        task_result: { videos: [{ id: '1', url: 'https://cdn.test/out.mp4', duration: '5' }] },
      })
      const wrapper = mount(AdminKlingPanel)
      await vi.advanceTimersByTimeAsync(0)
      expect(wrapper.text()).toContain('kling-v3-omni')

      await buttonByText(wrapper, '填入文生示例').trigger('click')
      expect(wrapper.find('.prompt-input').element).toHaveProperty(
        'value',
        expect.stringContaining('机械狐狸'),
      )

      await wrapper.find('.submit-btn').trigger('click')
      await vi.advanceTimersByTimeAsync(0)
      expect(submitKlingTask).toHaveBeenCalledWith(
        expect.objectContaining({
          prompt: expect.stringContaining('机械狐狸'),
          images: [],
          videos: [],
          duration: 5,
          mode: 'pro',
          aspectRatio: '16:9',
          sound: 'off',
          cfgScale: 0.5,
        }),
      )
      expect(wrapper.text()).toContain('k-task-1')

      await vi.advanceTimersByTimeAsync(5000)
      expect(queryKlingTask).toHaveBeenCalledWith('k-task-1')
      expect(wrapper.find('video').attributes('src')).toBe('https://cdn.test/out.mp4')

      const saved = JSON.parse(localStorage.getItem('kling-test-history') ?? '[]')
      expect(saved[0]).toMatchObject({
        taskId: 'k-task-1',
        status: 'succeed',
        videoUrl: 'https://cdn.test/out.mp4',
      })
      wrapper.unmount()
    } finally {
      vi.useRealTimers()
    }
  })

  it('forces sound off when a reference video url is provided', async () => {
    vi.mocked(fetchKlingStatus).mockResolvedValue(configuredStatus)
    const wrapper = mount(AdminKlingPanel)
    await vi.waitFor(() => expect(fetchKlingStatus).toHaveBeenCalled())
    await flush()

    // 先开声音，再填参考视频 → 声音被强制 off 且选择框禁用（接口约束）
    const soundSelect = wrapper
      .findAll('select')
      .find((item) => (item.element as HTMLSelectElement).value === 'off')!
    await soundSelect.setValue('on')
    const videoInput = wrapper.find('input[placeholder*="视频 URL"]')
    await videoInput.setValue('https://x.test/motion.mp4')
    await flush()
    expect((soundSelect.element as HTMLSelectElement).value).toBe('off')
    expect(soundSelect.attributes('disabled')).toBeDefined()
    wrapper.unmount()
  })

  it('renders stored history and refreshes entry status', async () => {
    localStorage.setItem(
      'kling-test-history',
      JSON.stringify([
        {
          taskId: 'k-old-7',
          time: '2026/8/16 10:00:00',
          summary: '5s · pro · 16:9 · 声off',
          status: 'processing',
          videoUrl: '',
        },
      ]),
    )
    vi.mocked(fetchKlingStatus).mockResolvedValue(configuredStatus)
    vi.mocked(queryKlingTask).mockResolvedValue({
      task_id: 'k-old-7',
      task_status: 'succeed',
      task_result: { videos: [{ id: '1', url: 'https://cdn.test/old.mp4', duration: '5' }] },
    })
    const wrapper = mount(AdminKlingPanel)
    await vi.waitFor(() => expect(wrapper.text()).toContain('k-old-7'.slice(-8)))

    await buttonByText(wrapper, '刷新').trigger('click')
    await vi.waitFor(() => expect(queryKlingTask).toHaveBeenCalledWith('k-old-7'))
    await flush()

    expect(wrapper.find('.kling-table').text()).toContain('succeed')
    expect(wrapper.find('.kling-table a').attributes('href')).toBe('https://cdn.test/old.mp4')
    wrapper.unmount()
  })
})
