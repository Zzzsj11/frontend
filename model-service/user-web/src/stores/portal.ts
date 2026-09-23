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
interface Key {
  id: string
  name: string
  key_prefix: string
  enabled: boolean
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
interface Job {
  id: string
  client_id: string
  model: string
  status: string
  usage: unknown
  billing: Bill
  created_at: string
  error: string | null
}
interface Ledger {
  id: string
  kind: string
  client_id: string
  job_id: string | null
  points: string
  monthly_after: string
  extra_after: string
  reason: string
  created_at: string
  evidence: unknown
}
export const labels: Record<string, string> = {
  monthly_reset: '月度重置',
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
    } | null,
    models: [] as Model[],
    jobs: [] as Job[],
    ledger: [] as Ledger[],
    total: 0,
    ledgerTotal: 0,
    page: 1,
    ledgerPage: 1,
    loading: false,
    error: '',
    message: '',
  }),
  actions: {
    async execute(action: () => Promise<void>) {
      this.loading = true
      this.error = ''
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
    async auth(mode: string, username: string, password: string) {
      await this.execute(async () => {
        if (mode === 'register') {
          await api('/register', 'POST', { username, password })
          this.message = '注册成功，请登录。API Key 由管理员生成与绑定。'
          return
        }
        const result = await api<{ access_token: string }>('/login', 'POST', { username, password })
        setToken(result.access_token)
        this.message = ''
        await this.refresh()
      })
    },
    async refresh() {
      this.user = await api<NonNullable<typeof this.user>>('/me')
      if (this.user.must_change_password) {
        this.jobs = []
        this.ledger = []
        this.total = this.ledgerTotal = 0
        return
      }
      const [jobs, ledger] = await Promise.all([
        api<{ items: Job[]; total: number }>(`/jobs?page=${this.page}`),
        api<{ items: Ledger[]; total: number }>(`/ledger?page=${this.ledgerPage}`),
      ])
      this.jobs = jobs.items
      this.total = jobs.total
      this.ledger = ledger.items
      this.ledgerTotal = ledger.total
    },
    async reload() {
      await this.execute(() => this.refresh())
    },
    async changePassword(current_password: string, new_password: string, confirmation: string) {
      await this.execute(async () => {
        await api('/change-password', 'POST', { current_password, new_password, confirmation })
        setToken('')
        this.user = null
        this.jobs = []
        this.ledger = []
        this.total = this.ledgerTotal = 0
        this.message = '密码已更新，请使用新密码登录。'
      })
    },
    async logout() {
      await this.execute(async () => {
        await api('/logout', 'POST')
        setToken('')
        this.user = null
        this.jobs = []
        this.ledger = []
        this.total = 0
        this.ledgerTotal = 0
      })
    },
  },
})
