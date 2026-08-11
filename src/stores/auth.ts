import { defineStore } from 'pinia'
import {
  apiRequest,
  loginRequest,
  logoutRequest,
  restoreSession,
  type AuthUser,
} from '../api/client'
export interface AccountBalance {
  available: boolean
  balance: string | null
  balanceDisplay: string
  currency: string
  updatedAt: string
  message?: string | null
}
export const useAuthStore = defineStore('auth', {
  state: () => ({
    user: null as AuthUser | null,
    ready: false,
    loading: false,
    balance: null as AccountBalance | null,
    balanceLoading: false,
  }),
  getters: { authenticated: (state) => Boolean(state.user) },
  actions: {
    async initialize() {
      if (!this.ready) {
        this.user = await restoreSession().catch(() => null)
        this.ready = true
        if (this.user) void this.loadBalance()
      }
    },
    async login(username: string, password: string) {
      this.loading = true
      try {
        this.user = (await loginRequest(username, password)).user
        void this.loadBalance(true)
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
    async logout() {
      await logoutRequest()
      this.user = null
      this.balance = null
    },
  },
})
