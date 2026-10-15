import { defineStore } from 'pinia'
import {
  apiRequest,
  loginRequest,
  logoutRequest,
  restoreSession,
  type AuthUser,
} from '../api/client'
import { useProjectStore } from './project'
export interface KeyQuotaInfo {
  keyMasked: string
  keyName: string | null
  quotaAmt: number | null
  usedAmt: number | null
  remaining: number | null
  remainingDisplay: string
  updatedAt?: string
  stale?: boolean
  warning?: string | null
}
export interface AccountBalance {
  available: boolean
  balance: string | null
  balanceDisplay: string
  currency: string
  updatedAt: string
  message?: string | null
  key?: KeyQuotaInfo | null
  keyError?: string | null
  providers?: {
    yinghe: AccountBalance
  }
}
export interface AllInOneCredits {
  available: boolean
  remaining?: string
  remainingDisplay?: string
  monthlyPoints?: string
  spentPoints?: string
  reservedPoints?: string
  keyMasked?: string
  updatedAt?: string
  message?: string
}
export const useAuthStore = defineStore('auth', {
  state: () => ({
    user: null as AuthUser | null,
    ready: false,
    loading: false,
    balance: null as AccountBalance | null,
    balanceLoading: false,
    allInOneCredits: null as AllInOneCredits | null,
  }),
  getters: { authenticated: (state) => Boolean(state.user) },
  actions: {
    async initialize() {
      if (!this.ready) {
        this.user = await restoreSession().catch(() => null)
        this.ready = true
        if (this.user && !this.user.mustChangePassword) {
          void this.loadBalance()
          void this.loadAllInOneCredits()
        }
      }
    },
    async login(username: string, password: string) {
      this.loading = true
      try {
        this.user = (await loginRequest(username, password)).user
        if (!this.user.mustChangePassword) {
          void this.loadBalance()
          void this.loadAllInOneCredits()
        }
      } finally {
        this.loading = false
        this.ready = true
      }
    },
    async loadBalance(force = false) {
      if (!this.user || this.balanceLoading) return
      this.balanceLoading = true
      try {
        this.balance = await apiRequest<AccountBalance>(
          `/account/balance${force ? '?force=true' : ''}`,
        )
      } finally {
        this.balanceLoading = false
      }
    },
    async loadAllInOneCredits() {
      if (!this.user) return
      this.allInOneCredits = await apiRequest<AllInOneCredits>(
        '/account/all-in-one-credits',
        {},
        true,
        [404],
      ).catch(() => ({ available: false, message: '平台积分暂不可用' }))
    },
    async logout() {
      const uid = this.user?.id
      await logoutRequest()
      this.user = null
      this.balance = null
      this.allInOneCredits = null
      // 清空用户相关的 localStorage
      if (uid) {
        localStorage.removeItem(`mv_sidebar_song_${uid}`)
        localStorage.removeItem(`mv_sidebar_task_${uid}`)
      }
      localStorage.removeItem('mv:pending-dh')
      // 清空工作区内存现场（项目列表/分镜/角色/缓存），防止下一账号看到上一账号数据
      useProjectStore().resetWorkspace()
    },
  },
})
