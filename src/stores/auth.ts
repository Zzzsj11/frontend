import { defineStore } from 'pinia'
import { loginRequest, logoutRequest, restoreSession, type AuthUser } from '../api/client'
export const useAuthStore = defineStore('auth', {
  state: () => ({ user: null as AuthUser | null, ready: false, loading: false }),
  getters: { authenticated: (state) => Boolean(state.user) },
  actions: {
    async initialize() { if (!this.ready) { this.user = await restoreSession().catch(() => null); this.ready = true } },
    async login(username: string, password: string) { this.loading = true; try { this.user = (await loginRequest(username, password)).user } finally { this.loading = false; this.ready = true } },
    async logout() { await logoutRequest(); this.user = null },
  },
})
