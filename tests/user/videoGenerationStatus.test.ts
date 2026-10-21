import { mount } from '@vue/test-utils'
import { afterEach, expect, it, vi } from 'vitest'
import VideoGenerationStatus from '../../src/components/VideoGenerationStatus.vue'

afterEach(() => vi.useRealTimers())
it('shows the actual phase and elapsed time without hiding an existing version', async () => {
  vi.useFakeTimers()
  vi.setSystemTime(new Date('2026-10-21T03:00:05Z'))
  const wrapper = mount(VideoGenerationStatus, {
    props: { phase: 'platform_queued', submittedAt: '2026-10-21T02:59:00Z', hasAssets: true },
  })
  expect(wrapper.text()).toContain('平台排队中，已等待 1分05秒')
  expect(wrapper.text()).toContain('已有素材可预览')
  await vi.advanceTimersByTimeAsync(1000)
  expect(wrapper.text()).toContain('1分06秒')
  await wrapper.setProps({ phase: 'manual_review' })
  expect(wrapper.text()).toContain('状态核对中')
  wrapper.unmount()
  expect(vi.getTimerCount()).toBe(0)
})
