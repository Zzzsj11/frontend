import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import DeploymentBadge from '../../src/components/DeploymentBadge.vue'

beforeEach(() => vi.useFakeTimers())
afterEach(() => {
  vi.useRealTimers()
  vi.restoreAllMocks()
})

describe('DeploymentBadge', () => {
  it('展示部署完成时间和版本短号', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({
          version: 'git-41d768b5a37bcc70ddf49f7f898ad5bce94fb277',
          deployedAt: '2026-08-20T12:34:00Z',
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    )
    const wrapper = mount(DeploymentBadge, {
      props: { currentVersion: 'git-41d768b5a37bcc70ddf49f7f898ad5bce94fb277' },
    })
    await flushPromises()
    expect(wrapper.text()).toContain('部署 08/20 20:34 · 41d768b')
    expect(wrapper.attributes('title')).toContain('版本标识：41d768b')
    wrapper.unmount()
  })

  it('浏览器构建版本与线上版本不同时提示用户刷新', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({ version: 'git-new-release-abcdef', deployedAt: '2026-09-06T08:45:00Z' }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    )
    const wrapper = mount(DeploymentBadge, {
      props: { currentVersion: 'git-old-release-123456' },
    })
    await flushPromises()

    const button = wrapper.get('button[data-test="deployment-badge"]')
    expect(button.text()).toContain('发现新版本，点击刷新')
    expect(button.attributes('aria-label')).toBe('发现新版本，点击刷新页面')
    expect(button.attributes('title')).toContain('当前版本：old-rel')
    expect(button.attributes('title')).toContain('最新版本：new-rel')
    wrapper.unmount()
  })

  it('定时检查版本并标记轮询请求', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ version: 'git-same', deployedAt: null }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    const wrapper = mount(DeploymentBadge, {
      props: { currentVersion: 'git-same', checkIntervalMs: 1_000 },
    })
    await flushPromises()
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(new Headers(fetchMock.mock.calls[0]?.[1]?.headers).get('X-Polling')).toBe('1')

    await vi.advanceTimersByTimeAsync(1_000)
    await flushPromises()
    expect(fetchMock).toHaveBeenCalledTimes(2)
    wrapper.unmount()
  })
})
