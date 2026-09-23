import { api } from './client'

export type Currency = 'CNY' | 'USD' | 'POINTS' | 'UNKNOWN'
export interface BalancePolicy {
  currency: Currency
  usd_cny: string
  points_per_unit: string | null
  points_currency: 'CNY' | 'USD'
}
export interface ChannelBalance extends BalancePolicy {
  id: string
  name: string
  channel: string
  balance: string | null
  cny_balance: string | null
  key_masked: string | null
  quota: {
    name: string
    limit: string | null
    used: string
    remaining: string | null
    unlimited: boolean
  } | null
  quota_error: string | null
  source: 'provider' | 'manual' | null
  queried_at: string | null
  attempted_at: string | null
  stale: boolean
  error: string | null
  automatic: boolean
  conversion_pending: boolean
}
export const listBalances = () => api<ChannelBalance[]>('/channel-balances')
export const savePolicy = (id: string, policy: BalancePolicy) =>
  api<ChannelBalance>(`/channel-balances/${encodeURIComponent(id)}`, 'PATCH', policy)
export const refreshBalance = (id: string) =>
  api<{ scheduled_at: string }>(`/channel-balances/${encodeURIComponent(id)}/refresh`, 'POST')
export const recordBalance = (id: string, balance: string, note: string) =>
  api<ChannelBalance>(`/channel-balances/${encodeURIComponent(id)}/manual`, 'POST', {
    balance,
    note,
  })
