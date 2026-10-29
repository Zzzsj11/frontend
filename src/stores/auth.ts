import { defineStore } from 'pinia'
import {
  apiRequest,
  loginRequest,
  logoutRequest,
  restoreSession,
  type AuthUser,
} from '../api/client'
import { useProjectStore } from './project'
import { useGenerationPreferences } from './generationPreferences'
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
const balanceRequests = new WeakMap<
  object,
  { userId: string; promise: Promise<AccountBalance | null> }
>()

export const useAuthStore = defineStore('auth', {
  state: () => ({
    user: null as AuthUser | null,
    ready: false,
    loading: false,
    balance: null as AccountBalance | null,
    balanceLoading: false,
    allInOneCredits: null as AllInOneCredits | null,
  }),
  getters: {
    authenticated: (state) => Boolean(state.user),
    canAccessAdmin: (state) =>
      Boolean(
        state.user?.isSuperAdmin ||
        state.user?.permissions?.some((permission) =>
          ['song_emotions.read', 'storyboard_options.read'].includes(permission),
        ),
      ),
  },
  actions: {
    async initialize() {
      if (!this.ready) {
        this.user = await restoreSession().catch(() => null)
        this.ready = true
        if (this.user && !this.user.mustChangePassword) {
          void this.loadAllInOneCredits()
          await useGenerationPreferences().load(this.user.id)
        }
      }
    },
    async login(username: string, password: string) {
      this.loading = true
      try {
        this.user = (await loginRequest(username, password)).user
        if (!this.user.mustChangePassword) {
          void this.loadAllInOneCredits()
          await useGenerationPreferences().load(this.user.id)
        }
      } finally {
        this.loading = false
        this.ready = true
      }
    },
    async loadBalance(force = false): Promise<AccountBalance | null> {
      const userId = this.user?.id
      if (!userId) return null
      const pending = balanceRequests.get(this)
      if (pending?.userId === userId) return pending.promise
      this.balanceLoading = true
      const promise = apiRequest<AccountBalance>(`/account/balance${force ? '?force=true' : ''}`)
        .then((balance) => {
          if (this.user?.id !== userId) return null
          this.balance = balance
          return balance
        })
        .finally(() => {
          if (balanceRequests.get(this)?.promise === promise) {
            balanceRequests.delete(this)
            this.balanceLoading = false
          }
        })
      balanceRequests.set(this, { userId, promise })
      return promise
    },
    async loadAllInOneCredits() {
      const userId = this.user?.id
      if (!userId) return
      const credits = await apiRequest<AllInOneCredits>(
        '/account/all-in-one-credits',
        {},
        true,
        [404],
      ).catch(() => ({ available: false, message: '平台积分暂不可用' }))
      if (this.user?.id === userId) this.allInOneCredits = credits
    },
    async logout() {
      const uid = this.user?.id
      await logoutRequest()
      this.user = null
      useGenerationPreferences().$reset()
      this.balance = null
      this.allInOneCredits = null
      // 清空用户相关的 localStorage
      if (uid) {
        localStorage.removeItem(`mv_sidebar_song_${uid}`)
        localStorage.removeItem(`mv_sidebar_task_${uid}`)
      }
      localStorage.removeItem('mv:pending-dh')
      if (uid) localStorage.removeItem(`mv:pending-dh:${uid}`)
      // 清空工作区内存现场（项目列表/分镜/角色/缓存），防止下一账号看到上一账号数据
      useProjectStore().resetWorkspace()
    },
  },
})
