import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import DeploymentBadge from '../../src/components/DeploymentBadge.vue'

afterEach(() => vi.restoreAllMocks())

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
    const wrapper = mount(DeploymentBadge)
    await flushPromises()
    expect(wrapper.text()).toContain('部署 08/20 20:34 · 41d768b')
    expect(wrapper.attributes('title')).toContain('41d768b5a37bcc70ddf49f7f898ad5bce94fb277')
  })
})
