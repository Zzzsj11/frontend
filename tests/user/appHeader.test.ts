import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import AppHeader from '../../src/components/AppHeader.vue'
import { useAuthStore } from '../../src/stores/auth'

describe('AppHeader provider balances', () => {
  beforeEach(() => setActivePinia(createPinia()))
  afterEach(() => vi.useRealTimers())

  it('只展示 All in one Key 剩余积分', () => {
    const auth = useAuthStore()
    auth.user = {
      id: 'u1',
      username: 'dev01',
      displayName: 'Dev 01',
      role: 'user',
      mustChangePassword: false,
    }
    auth.allInOneCredits = {
      available: true,
      remaining: '123.5',
      remainingDisplay: '123.50',
      monthlyPoints: '200',
      spentPoints: '76.5',
      reservedPoints: '0',
      keyMasked: 'ms_test***',
    }
    const wrapper = mount(AppHeader, {
      global: {
        stubs: { RouterLink: { template: '<a><slot /></a>' }, DeploymentBadge: true },
      },
    })
    expect(wrapper.findAll('.balance-pill')).toHaveLength(1)
    expect(wrapper.find('.balance-pill.yinghe').exists()).toBe(false)
    const allInOne = wrapper.get('.balance-pill.all-in-one')
    expect(allInOne.text()).toContain('All in one')
    expect(allInOne.text()).toContain('123.50')
    expect(allInOne.attributes('title')).toContain('当前 Key ms_test***')
    wrapper.unmount()
  })

  it('每五分钟刷新平台积分并支持手动刷新', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-09-16T12:00:00Z'))
    const auth = useAuthStore()
    auth.user = {
      id: 'u1',
      username: 'dev01',
      displayName: 'Dev 01',
      role: 'user',
      mustChangePassword: false,
    }
    auth.allInOneCredits = {
      available: true,
      remainingDisplay: '100.00',
      updatedAt: new Date().toISOString(),
    }
    const loadCredits = vi.spyOn(auth, 'loadAllInOneCredits').mockResolvedValue()
    const wrapper = mount(AppHeader, {
      global: {
        stubs: { RouterLink: { template: '<a><slot /></a>' }, DeploymentBadge: true },
      },
    })

    await vi.advanceTimersByTimeAsync(60_000)
    expect(loadCredits).not.toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(4 * 60_000)
    expect(loadCredits).toHaveBeenCalledTimes(1)

    expect(wrapper.get('.balance-pill.all-in-one .balance-value').text()).toBe('100.00')
    await wrapper.get('.balance-pill.all-in-one').trigger('click')
    expect(loadCredits).toHaveBeenCalledTimes(2)
    wrapper.unmount()
  })

  it('余额不可用时显示占位和原因，仍可手动刷新', async () => {
    const auth = useAuthStore()
    auth.user = {
      id: 'u1',
      username: 'dev01',
      displayName: 'Dev 01',
      role: 'user',
      mustChangePassword: false,
    }
    auth.allInOneCredits = {
      available: false,
      updatedAt: new Date().toISOString(),
      message: '积分查询暂时不可用',
    }
    const loadCredits = vi.spyOn(auth, 'loadAllInOneCredits').mockResolvedValue()
    const wrapper = mount(AppHeader, {
      global: {
        stubs: { RouterLink: { template: '<a><slot /></a>' }, DeploymentBadge: true },
      },
    })

    const balance = wrapper.get('.balance-pill.all-in-one')
    expect(balance.get('.balance-value').text()).toBe('--')
    expect(balance.attributes('title')).toBe('积分查询暂时不可用')
    expect(balance.find('[data-test="key-quota"]').exists()).toBe(false)
    expect(wrapper.get('.user-name').text()).toBe('Dev 01')
    await balance.trigger('click')
    expect(loadCredits).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })
})
