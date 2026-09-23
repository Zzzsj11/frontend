import { defineStore } from 'pinia'
import { api, setToken } from '../api/client'
export interface Model {
  id: string
  kind: string
  channel: string
  enabled: boolean
  concurrency: number
  capabilities: Record<string, unknown>
}
export interface Client {
  id: string
  name: string
  key_prefix: string
  enabled: boolean
  concurrency: number
  require_agent: boolean
  allowed_models: string[]
}
export interface Job {
  id: string
  model: string
  status: string
  origin: string
  agent_name: string
  agent_run_id: string
  user_id: string
  billing: { status: string; points: string | null; reserved_points: string }
  usage: Record<string, unknown>
  error: string | null
  created_at: string
}
export const useControl = defineStore('control', {
  state: () => ({
    authenticated: false,
    loading: false,
    error: '',
    models: [] as Model[],
    clients: [] as Client[],
    jobs: [] as Job[],
    total: 0,
    page: 1,
    origin: '',
    status: '',
    run: '',
    revealedKey: '',
    detail: null as unknown,
    counts: [] as { status: string; origin: string; count: number }[],
    audits: [] as {
      id: string
      actor: string
      action: string
      target: string
      created_at: string
    }[],
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
    async login(username: string, password: string) {
      await this.execute(async () => {
        const data = await api<{ access_token: string }>('/login', 'POST', { username, password })
        setToken(data.access_token)
        this.authenticated = true
        await this.refresh()
      })
    },
    logout() {
      setToken('')
      this.$reset()
    },
    async refresh() {
      const [models, clients, jobs, overview, audits] = await Promise.all([
        api<Model[]>('/models'),
        api<Client[]>('/clients'),
        api<{ items: Job[]; total: number }>(
          `/jobs?page=${this.page}&origin=${encodeURIComponent(this.origin)}&status=${encodeURIComponent(this.status)}&agent_run_id=${encodeURIComponent(this.run)}`,
        ),
        api<{ counts: { status: string; origin: string; count: number }[] }>('/overview'),
        api<{ id: string; actor: string; action: string; target: string; created_at: string }[]>(
          '/audits',
        ),
      ])
      this.models = models
      this.clients = clients
      this.jobs = jobs.items
      this.total = jobs.total
      this.counts = overview.counts
      this.audits = audits
    },
    async reload() {
      await this.execute(() => this.refresh())
    },
    async changeModel(model: Model, changes: Partial<Model>) {
      await this.execute(async () => {
        await api(`/models/${encodeURIComponent(model.id)}`, 'PATCH', changes)
        await this.refresh()
      })
    },
    async createClient(name: string, require_agent: boolean) {
      await this.execute(async () => {
        const data = await api<{ api_key: string }>('/clients', 'POST', { name, require_agent })
        this.revealedKey = data.api_key
        await this.refresh()
      })
    },
    async toggleClient(client: Client) {
      await this.execute(async () => {
        await api(`/clients/${client.id}`, 'PATCH', { enabled: !client.enabled })
        await this.refresh()
      })
    },
    async inspect(job: Job) {
      await this.execute(async () => {
        this.detail = await api(`/jobs/${job.id}`)
      })
    },
    async recover(job: Job) {
      await this.execute(async () => {
        await api(`/jobs/${job.id}/recover`, 'POST')
        await this.refresh()
      })
    },
  },
})
