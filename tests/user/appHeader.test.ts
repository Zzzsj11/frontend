import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'

import AppHeader from '../../src/components/AppHeader.vue'
import { useAuthStore } from '../../src/stores/auth'

describe('AppHeader provider balances', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('同时展示英和与 PPIO 两个余额胶囊', () => {
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
        ppio: {
          available: true,
          rawBalance: '1000000',
          balance: '125',
          balanceDisplay: '125.00',
          unitScale: 10000,
          currency: 'CNY',
          updatedAt: '',
          details: {
            cashBalance: 80,
            creditLimit: 20,
            pendingCharges: 0,
            outstandingInvoices: 0,
            accountAvailableBalance: 100,
            modelCreditBalance: 25,
          },
          rawDetails: {
            cashBalance: '800000',
            creditLimit: '200000',
            pendingCharges: '0',
            outstandingInvoices: '0',
          },
        },
      },
    }
    const wrapper = mount(AppHeader, {
      global: {
        stubs: { RouterLink: { template: '<a><slot /></a>' }, DeploymentBadge: true },
      },
    })
    expect(wrapper.text()).toContain('英和')
    expect(wrapper.text()).toContain('2626.47')
    expect(wrapper.text()).toContain('yh-test*** 余 658.96')
    expect(wrapper.get('[data-test="ppio-balance"]').text()).toContain('PPIO')
    expect(wrapper.get('[data-test="ppio-balance"]').text()).toContain('125.00')
    expect(wrapper.get('[data-test="ppio-balance"]').attributes('title')).toContain('现金 ¥80')
    expect(wrapper.get('[data-test="ppio-balance"]').attributes('title')).toContain('模型额度 ¥25')
  })
})
