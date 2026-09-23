import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import AppHeader from '../../src/components/AppHeader.vue'
import { useAuthStore } from '../../src/stores/auth'

describe('AppHeader provider balances', () => {
  beforeEach(() => setActivePinia(createPinia()))
  afterEach(() => vi.useRealTimers())

  it('仅展示英和余额胶囊及当前 Key 额度', () => {
    const auth = useAuthStore()
    auth.user = {
      id: 'u1',
      username: 'dev01',
      displayName: 'Dev 01',
      role: 'user',
      mustChangePassword: false,
    }
    auth.balance = {
      available: true,
      balance: '2626.47',
      balanceDisplay: '2626.47',
      currency: 'CNY',
      updatedAt: '',
      key: {
        keyMasked: 'yh-test***',
        keyName: '视频 Key',
        quotaAmt: 1000,
        usedAmt: 341.04,
        remaining: 658.96,
        remainingDisplay: '658.96',
      },
      providers: {
        yinghe: {
          available: true,
          balance: '2626.47',
          balanceDisplay: '2626.47',
          currency: 'CNY',
          updatedAt: '',
          key: {
            keyMasked: 'yh-test***',
            keyName: '视频 Key',
            quotaAmt: 1000,
            usedAmt: 341.04,
            remaining: 658.96,
            remainingDisplay: '658.96',
          },
        },
      },
    }
    const wrapper = mount(AppHeader, {
      global: {
        stubs: { RouterLink: { template: '<a><slot /></a>' }, DeploymentBadge: true },
      },
    })
    const balance = wrapper.get('.balance-pill.yinghe')
    expect(wrapper.findAll('.balance-pill')).toHaveLength(1)
    expect(balance.text()).toContain('英和')
    expect(balance.get('.balance-value').text()).toBe('2626.47')
    expect(balance.get('[data-test="key-quota"]').text()).toBe('yh-test*** 余 658.96')
    expect(balance.attributes('title')).toContain('当前 Key yh-test***（视频 Key）')
    expect(balance.attributes('title')).toContain('月度已用 341.04 / 限额 1000')
    wrapper.unmount()
  })

  it('自动刷新每五分钟使用缓存，只有用户点击才强制查询', async () => {
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
    auth.balance = {
      available: true,
      balance: '100',
      balanceDisplay: '100.00',
      currency: 'CNY',
      updatedAt: new Date().toISOString(),
    }
    const loadBalance = vi.spyOn(auth, 'loadBalance').mockResolvedValue()
    const wrapper = mount(AppHeader, {
      global: {
        stubs: { RouterLink: { template: '<a><slot /></a>' }, DeploymentBadge: true },
      },
    })

    await vi.advanceTimersByTimeAsync(60_000)
    expect(loadBalance).not.toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(4 * 60_000)
    expect(loadBalance).toHaveBeenCalledWith(false)

    expect(wrapper.get('.balance-pill.yinghe .balance-value').text()).toBe('100.00')
    await wrapper.get('.balance-pill.yinghe').trigger('click')
    expect(loadBalance).toHaveBeenLastCalledWith(true)
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
    auth.balance = {
      available: false,
      balance: null,
      balanceDisplay: '--',
      currency: 'CNY',
      updatedAt: new Date().toISOString(),
      message: '余额查询暂时不可用',
    }
    const loadBalance = vi.spyOn(auth, 'loadBalance').mockResolvedValue()
    const wrapper = mount(AppHeader, {
      global: {
        stubs: { RouterLink: { template: '<a><slot /></a>' }, DeploymentBadge: true },
      },
    })

    const balance = wrapper.get('.balance-pill.yinghe')
    expect(balance.get('.balance-value').text()).toBe('--')
    expect(balance.attributes('title')).toBe('余额查询暂时不可用')
    expect(balance.find('[data-test="key-quota"]').exists()).toBe(false)
    expect(wrapper.get('.user-name').text()).toBe('Dev 01')
    await balance.trigger('click')
    expect(loadBalance).toHaveBeenCalledWith(true)
    wrapper.unmount()
  })
})
