import { defineStore } from 'pinia'
import { api, setToken } from '../api/client'
export interface Rate {
  label: string
  path: string
  unit: string
  cny: string
  optional?: boolean
  subtract?: string[]
}
export interface Price {
  id?: string
  selector?: Record<string, string>
  description: string
  source: string
  confirmed: boolean
  reserve_points: string
  rates: Rate[]
  actual_cny_path: string
}
export interface Model {
  id: string
  kind: string
  enabled: boolean
  capabilities: Record<string, unknown>
  pricing: Price[]
}
export interface Key {
  id: string
  name: string
  key_prefix: string
  enabled: boolean
  spent_points: string
  monthly_points: string
  monthly_balance: string
  extra_balance: string
  reserved_points: string
  available_points: string
  billing_month: string
}
interface Bill {
  status: string
  points: string | null
  cny: string | null
  reserved_points: string
  rule: Price
}
export interface TaskContent {
  texts: { role: string; text: string }[]
  media: { kind: string; url: string; role: string; thumbnail_url?: string }[]
}
export interface Job {
  kind?: string
  request_content?: TaskContent
  result_content?: TaskContent
  key_name: string
  id: string
  client_id: string
  model: string
  status: string
  usage: unknown
  billing: Bill
  created_at: string
  error: string | null
}
export interface Ledger {
  key_name: string
  id: string
  kind: string
  client_id: string
  job_id: string | null
  points: string | null
  monthly_after: string | null
  extra_after: string | null
  task_kind: string
  status: string
  model: string
  reserved_points?: string
  row_type: string
  reason: string
  created_at: string
  evidence: unknown
}
export const labels: Record<string, string> = {
  monthly_reset: '月度重置',
  quota_adjust: '月上限调整',
  manual_credit: '临时增加',
  manual_debit: '临时扣减',
  task_charge: '任务消费',
  reconciliation: '账单校正',
  usage_priced: '按用量计价',
  settled: '已核账',
  pending_reconciliation: '待核账',
  reserved: '已预占',
  pending: '等待计费',
  text_to_video: '文生视频',
  image_to_video: '图生视频',
  reference_to_video: '参考图生视频',
  first_last_frame: '首尾帧视频',
  text_to_image: '文生图',
  image_to_image: '图生图',
  chat: '文本对话',
  edit: '续编 / 编辑',
}
export const usePortal = defineStore('portal', {
  state: () => ({
    user: null as {
      id: string
      username: string
      must_change_password: boolean
      keys: Key[]
      quota?: {
        monthly_points: string
        spent_points: string
        reserved_points: string
        available_points: string
        allocated_points: string
        key_count: number
        key_limit: number
        billing_month: string
      }
    } | null,
    models: [] as Model[],
    ledger: [] as Ledger[],
    ledgerTotal: 0,
    ledgerPage: 1,
    ledgerLimit: 10,
    ledgerKey: '',
    ledgerKind: '',
    historyKeys: [] as { id: string; name: string; deleted: boolean }[],
    loading: false,
    error: '',
    message: '',
    revealedKey: '',
  }),
  actions: {
    async execute(action: () => Promise<void>) {
      this.loading = true
      this.error = ''
      this.message = ''
      try {
        await action()
      } catch (e) {
        this.error = e instanceof Error ? e.message : '请求失败'
      } finally {
        this.loading = false
      }
    },
    async loadModels() {
      await this.execute(async () => {
        this.models = await api<Model[]>('/models')
      })
    },
    async auth(username: string, password: string) {
      this.revealedKey = ''
      await this.execute(async () => {
        const result = await api<{ access_token: string }>('/login', 'POST', { username, password })
        setToken(result.access_token)
        this.ledgerPage = 1
        this.ledgerKey = this.ledgerKind = ''
        this.historyKeys = []
        this.message = ''
        await this.refresh()
      })
    },
    async refresh() {
      this.user = await api<NonNullable<typeof this.user>>('/me')
      if (this.user.must_change_password) {
        this.ledger = []
        this.historyKeys = []
        this.ledgerKey = this.ledgerKind = ''
        this.ledgerPage = 1
        this.ledgerTotal = 0
        return
      }
      const [ledger, historyKeys] = await Promise.all([
        api<{ items: Ledger[]; total: number; page: number }>(
          `/activity?page=${this.ledgerPage}&limit=${this.ledgerLimit}&client_id=${encodeURIComponent(this.ledgerKey)}&kind=${encodeURIComponent(this.ledgerKind)}`,
        ),
        api<typeof this.historyKeys>('/history-keys'),
      ])
      this.ledger = ledger.items
      this.ledgerTotal = ledger.total
      this.ledgerPage = ledger.page
      this.historyKeys = historyKeys
    },
    async jobDetail(id: string) {
      return api<Job>(`/jobs/${encodeURIComponent(id)}`)
    },
    async reload() {
      await this.execute(() => this.refresh())
    },
    async createKey(name: string, monthly_points: string) {
      await this.execute(async () => {
        const data = await api<{ api_key: string }>('/keys', 'POST', { name, monthly_points })
        this.revealedKey = data.api_key
        await this.refresh()
      })
    },
    async setKeyQuota(id: string, points: string) {
      await this.execute(async () => {
        await api(`/keys/${id}/quota`, 'POST', { points })
        await this.refresh()
        this.message = 'Key 月上限已更新，本月消费记录保留。'
      })
    },
    async revokeKey(id: string) {
      await this.execute(async () => {
        await api(`/keys/${id}/revoke`, 'POST')
        this.revealedKey = ''
        await this.refresh()
      })
    },
    async deleteKey(id: string) {
      await this.execute(async () => {
        await api(`/keys/${id}`, 'DELETE')
        this.revealedKey = ''
        await this.refresh()
      })
    },
    async changePassword(current_password: string, new_password: string, confirmation: string) {
      await this.execute(async () => {
        await api('/change-password', 'POST', { current_password, new_password, confirmation })
        setToken('')
        this.revealedKey = ''
        this.user = null
        this.ledger = []
        this.historyKeys = []
        this.ledgerKey = this.ledgerKind = ''
        this.ledgerPage = 1
        this.ledgerTotal = 0
        this.message = '密码已更新，请使用新密码登录。'
      })
    },
    async logout() {
      await this.execute(async () => {
        await api('/logout', 'POST')
        setToken('')
        this.revealedKey = ''
        this.user = null
        this.ledger = []
        this.historyKeys = []
        this.ledgerKey = this.ledgerKind = ''
        this.ledgerPage = 1
        this.ledgerTotal = 0
      })
    },
  },
})
