<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { apiRequest } from '../api/client'
import AdminModelComparisonPanel from '../components/AdminModelComparisonPanel.vue'
import AdminPromptsPanel from '../components/AdminPromptsPanel.vue'
import AdminKlingPanel from '../components/AdminKlingPanel.vue'
import AdminRunningHubPanel from '../components/AdminRunningHubPanel.vue'
import AdminStoryboardOptionsPanel from '../components/AdminStoryboardOptionsPanel.vue'
import AdminServerMonitoringPanel from '../components/AdminServerMonitoringPanel.vue'
import AdminSideNav from '../components/AdminSideNav.vue'
import AdminSongEmotionProfilesPanel from '../components/AdminSongEmotionProfilesPanel.vue'
import AdminTopBar from '../components/AdminTopBar.vue'
import BaseModal from '../components/base/BaseModal.vue'
import { perfSnapshot } from '../perf'
import { useAuthStore } from '../stores/auth'
import type { AdminNavGroup, AdminNavItem } from '../types'

/** 管理后台列表行：各 tab 返回列不一致，未建模的列由 columns 动态渲染 */
interface AdminRow {
  id?: string
  model?: string
  status?: string
  stale?: boolean
  providerTaskId?: string
  dailyChatLimit?: number
  dailyImageLimit?: number
  dailyVideoLimit?: number
  adminRoleCodes?: string[]
  isSuperAdmin?: boolean
  [key: string]: unknown
}

/** 仪表盘与分页响应（users/models 等 tab 直接返回数组，见 rows） */
interface AdminData {
  total?: number
  items?: AdminRow[]
  users?: number
  projects?: number
  jobs?: number
  systemHumans?: number
  errors?: number
  usage?: { totalTokens?: number; inputTokens?: number; outputTokens?: number }
  jobStatuses?: unknown
}

/** 性能页：后端慢请求行 */
interface ReqLogRow {
  id: string
  method: string
  path: string
  statusCode: number
  durationMs: number
  createdAt: string
}

/** 性能页：后端接口耗时聚合行 */
interface ReqSummaryRow {
  method: string
  path: string
  count: number
  avgMs: number
  p95Ms: number
  maxMs: number
}

/** 接口耗时页：批次选项 */
interface ReqRun {
  runId: string
  requests: number
  avgMs: number
  maxMs: number
  errors: number
}

/** 请求详情弹窗数据 */
interface ReqDetail {
  method: string
  path: string
  statusCode: number
  durationMs: number
  createdAt: string
  runId?: string
  queryString?: string
  requestPayload?: unknown
  responseBody?: unknown
}

/** LLM 调用详情弹窗数据 */
interface LlmDetail {
  operation: string
  model: string
  status: string
  durationMs: number
  inputTokens: number
  outputTokens: number
  cachedInputTokens: number
  requestId?: string
  createdAt: string
  error?: string
  requestMessages?: { role: string; content: string }[]
  responseText?: string
}
type Tab =
  | 'dashboard'
  | 'users'
  | 'projects'
  | 'jobs'
  | 'usage'
  | 'models'
  | 'errors'
  | 'audit'
  | 'llm'
  | 'requests'
  | 'perf'
  | 'server'
  | 'prompts'
  | 'categories'
  | 'song-emotions'
  | 'runninghub'
  | 'kling'
  | 'chat-comparison'
const auth = useAuthStore()
const tab = ref<Tab>(auth.user?.isSuperAdmin ? 'dashboard' : 'song-emotions'),
  loading = ref(false),
  error = ref(''),
  data = ref<AdminData | null>(null)
/** 侧边导航分组（同类项合并为两级菜单）；新增页面时挂到对应组即可 */
const ALL_NAV_GROUPS: AdminNavGroup[] = [
  { key: 'overview', label: '总览', items: [{ key: 'dashboard', label: '仪表盘' }] },
  {
    key: 'business',
    label: '业务运营',
    items: [
      { key: 'projects', label: '项目' },
      { key: 'users', label: '用户' },
      { key: 'jobs', label: '生成任务' },
      { key: 'usage', label: '费用用量' },
    ],
  },
  {
    key: 'content',
    label: '内容配置',
    items: [
      { key: 'prompts', label: '提示词' },
      { key: 'categories', label: '通用分类' },
      { key: 'song-emotions', label: '歌曲情感库' },
      { key: 'models', label: '模型管理' },
    ],
  },
  {
    key: 'lab',
    label: '模型实验室',
    items: [
      { key: 'chat-comparison', label: 'Chat 模型对比' },
      { key: 'runninghub', label: 'H3 工作流' },
      { key: 'kling', label: 'Kling 测试' },
    ],
  },
  {
    key: 'system',
    label: '系统监控',
    items: [
      { key: 'errors', label: '错误日志' },
      { key: 'audit', label: '操作审计' },
      { key: 'llm', label: 'LLM 调用' },
      { key: 'requests', label: '接口耗时' },
      { key: 'perf', label: '性能' },
      { key: 'server', label: '服务器监控' },
    ],
  },
]
const NAV_GROUPS = computed<AdminNavGroup[]>(() => {
  if (auth.user?.isSuperAdmin) return ALL_NAV_GROUPS
  const contentItems: AdminNavItem[] = []
  if (auth.user?.permissions?.includes('storyboard_options.read'))
    contentItems.push({ key: 'categories', label: '通用分类' })
  if (auth.user?.permissions?.includes('song_emotions.read'))
    contentItems.push({ key: 'song-emotions', label: '歌曲情感库' })
  if (contentItems.length)
    return [
      {
        key: 'content',
        label: '内容配置',
        items: contentItems,
      },
    ]
  return []
})
const tabTitle = computed(
  () => NAV_GROUPS.value.flatMap((g) => g.items).find((i) => i.key === tab.value)?.label ?? '',
)
const groupTitle = computed(
  () => NAV_GROUPS.value.find((g) => g.items.some((i) => i.key === tab.value))?.label ?? '',
)
const llmFilters = ref({ projectTaskId: '', operation: '', status: '' })
const llmDetail = ref<LlmDetail | null>(null),
  detailLoading = ref(false)
const reqFilters = ref({ runId: '', path: '' })
const reqRuns = ref<ReqRun[]>([])
const reqDetail = ref<ReqDetail | null>(null)
const jobFilters = ref({ kind: '', status: '', q: '' })
const jobPage = ref(1)
const jobPageSize = 50
const notice = ref('')
const syncing = ref('')
/** 提示词 tab 自管数据，父级仅通过 token 递增触发其刷新 */
const promptsReloadToken = ref(0)
/** 通用 offset 分页：projects/errors/audit/llm/requests 共用，切 tab 重置 */
const pageOffset = ref(0)
const pageSize = 50
const pageCount = computed(() => Math.max(1, Math.ceil((data.value?.total || 0) / pageSize)))
const currentPage = computed(() => Math.floor(pageOffset.value / pageSize) + 1)
const isPagedTab = computed(() =>
  ['projects', 'errors', 'audit', 'llm', 'requests'].includes(tab.value),
)
const turnPage = (delta: number) => {
  pageOffset.value = Math.max(
    0,
    Math.min((pageCount.value - 1) * pageSize, pageOffset.value + delta * pageSize),
  )
  void load()
}
const llmEndpoint = computed(() => {
  const query = new URLSearchParams()
  if (llmFilters.value.projectTaskId.trim())
    query.set('projectTaskId', llmFilters.value.projectTaskId.trim())
  if (llmFilters.value.operation.trim()) query.set('operation', llmFilters.value.operation.trim())
  if (llmFilters.value.status) query.set('status', llmFilters.value.status)
  query.set('limit', String(pageSize))
  query.set('offset', String(pageOffset.value))
  return `/admin/llm-calls?${query.toString()}`
})
const jobsEndpoint = computed(() => {
  const query = new URLSearchParams()
  if (jobFilters.value.kind) query.set('kind', jobFilters.value.kind)
  if (jobFilters.value.status) query.set('status', jobFilters.value.status)
  if (jobFilters.value.q.trim()) query.set('q', jobFilters.value.q.trim())
  query.set('page', String(jobPage.value))
  query.set('page_size', String(jobPageSize))
  return `/admin/jobs?${query.toString()}`
})
const endpoint = computed(
  () =>
    ({
      dashboard: '/admin/dashboard',
      users: '/admin/users',
      projects: `/admin/projects?limit=${pageSize}&offset=${pageOffset.value}`,
      jobs: jobsEndpoint.value,
      usage: '/admin/usage',
      models: '/admin/models',
      errors: `/admin/api-errors?limit=${pageSize}&offset=${pageOffset.value}`,
      audit: `/admin/audit-logs?limit=${pageSize}&offset=${pageOffset.value}`,
      llm: llmEndpoint.value,
      requests: reqEndpoint.value,
      perf: '',
      server: '',
      prompts: '',
      categories: '',
      'song-emotions': '',
      runninghub: '',
      kling: '',
      'chat-comparison': '',
    })[tab.value],
)
const rows = computed<AdminRow[]>(() =>
  Array.isArray(data.value) ? (data.value as AdminRow[]) : data.value?.items || [],
)
const load = async () => {
  // 性能页不走通用 endpoint（数据为后端聚合 + 本会话快照）
  if (tab.value === 'perf') return loadPerf()
  // 提示词页由 AdminPromptsPanel 自管数据
  if (tab.value === 'prompts') {
    promptsReloadToken.value += 1
    return
  }
  // 通用分类/模型测试页由各自面板自管数据
  if (
    tab.value === 'categories' ||
    tab.value === 'song-emotions' ||
    tab.value === 'runninghub' ||
    tab.value === 'kling' ||
    tab.value === 'chat-comparison' ||
    tab.value === 'server'
  )
    return
  loading.value = true
  error.value = ''
  try {
    data.value = await apiRequest<AdminData>(endpoint.value)
  } catch (e) {
    error.value = e instanceof Error ? e.message : '加载失败'
  } finally {
    loading.value = false
  }
}
const select = async (key: string) => {
  const value = key as Tab
  tab.value = value
  pageOffset.value = 0
  if (value === 'requests') void loadReqRuns()
  if (value === 'perf') return void loadPerf()
  if (
    value === 'prompts' ||
    value === 'categories' ||
    value === 'song-emotions' ||
    value === 'runninghub' ||
    value === 'kling' ||
    value === 'chat-comparison' ||
    value === 'server'
  )
    return
  await load()
}
const reqEndpoint = computed(() => {
  const query = new URLSearchParams()
  if (reqFilters.value.runId) query.set('runId', reqFilters.value.runId)
  if (reqFilters.value.path.trim()) query.set('path', reqFilters.value.path.trim())
  query.set('limit', String(pageSize))
  query.set('offset', String(pageOffset.value))
  return `/admin/request-logs?${query.toString()}`
})
const loadReqRuns = async () => {
  try {
    reqRuns.value = await apiRequest<ReqRun[]>('/admin/request-logs/runs')
  } catch {
    reqRuns.value = []
  }
}
/** 性能页：后端慢请求 TOP + 接口耗时聚合 + 本浏览器会话性能快照 */
const backendSlow = ref<ReqLogRow[]>([])
const backendSummary = ref<ReqSummaryRow[]>([])
const frontPerf = ref(perfSnapshot())
const loadPerf = async () => {
  loading.value = true
  error.value = ''
  try {
    const [summary, slow] = await Promise.all([
      apiRequest<ReqSummaryRow[]>('/admin/request-logs/summary?hours=24&minCount=2&limit=30'),
      apiRequest<{ items: ReqLogRow[] }>(
        '/admin/request-logs?minMs=1000&orderBy=duration&limit=30',
      ),
    ])
    backendSummary.value = summary
    backendSlow.value = slow.items || []
    frontPerf.value = perfSnapshot()
  } catch (e) {
    error.value = e instanceof Error ? e.message : '加载失败'
  } finally {
    loading.value = false
  }
}
const openReqDetail = async (row: AdminRow) => {
  detailLoading.value = true
  reqDetail.value = null
  try {
    reqDetail.value = await apiRequest<ReqDetail>(`/admin/request-logs/${row.id}`)
  } catch (e) {
    error.value = e instanceof Error ? e.message : '详情加载失败'
  } finally {
    detailLoading.value = false
  }
}
const openLlmDetail = async (row: AdminRow) => {
  detailLoading.value = true
  llmDetail.value = null
  try {
    llmDetail.value = await apiRequest<LlmDetail>(`/admin/llm-calls/${row.id}`)
  } catch (e) {
    error.value = e instanceof Error ? e.message : '详情加载失败'
  } finally {
    detailLoading.value = false
  }
}
const toggleModel = async (row: AdminRow) => {
  await apiRequest(`/admin/models/${row.id}`, {
    method: 'PATCH',
    body: JSON.stringify({ status: row.status === 'active' ? 'disabled' : 'active' }),
  })
  await load()
}
const searchJobs = () => {
  jobPage.value = 1
  void load()
}
const turnJobPage = (delta: number) => {
  jobPage.value = Math.max(1, jobPage.value + delta)
  void load()
}
const syncJob = async (row: AdminRow) => {
  syncing.value = row.id ?? ''
  notice.value = ''
  error.value = ''
  try {
    const result = await apiRequest<{ providerStatus?: string; action?: string }>(
      `/admin/jobs/${row.id}/sync`,
      { method: 'POST' },
    )
    const actionText: Record<string, string> = {
      recovered: '已挽回结果并落库',
      failed: '已同步失败原因',
      resumed: '已重新挂起轮询',
      unchanged: '状态一致无需处理',
      skipped: '任务正在执行中',
    }
    notice.value = `同步完成：供应商状态 ${result.providerStatus ?? '-'} · ${actionText[result.action ?? ''] || result.action}`
    await load()
  } catch (e) {
    error.value = e instanceof Error ? e.message : '同步失败'
  } finally {
    syncing.value = ''
  }
}
/** 用户 tab：创建用户表单 + 启用/禁用操作（原独立用户管理页合并至此） */
const userForm = ref({
  username: '',
  displayName: '',
  password: '',
  dailyChatLimit: 1000,
  dailyImageLimit: 1000,
  dailyVideoLimit: 1000,
})
const createUser = async () => {
  error.value = ''
  notice.value = ''
  try {
    await apiRequest('/admin/users', {
      method: 'POST',
      body: JSON.stringify({
        username: userForm.value.username,
        password: userForm.value.password,
        display_name: userForm.value.displayName,
        role: 'user',
        daily_chat_limit: userForm.value.dailyChatLimit,
        daily_image_limit: userForm.value.dailyImageLimit,
        daily_video_limit: userForm.value.dailyVideoLimit,
      }),
    })
    userForm.value = {
      username: '',
      displayName: '',
      password: '',
      dailyChatLimit: 1000,
      dailyImageLimit: 1000,
      dailyVideoLimit: 1000,
    }
    notice.value = '用户创建成功，首次登录需修改初始密码'
    await load()
  } catch (e) {
    error.value = e instanceof Error ? e.message : '创建失败'
  }
}
const saveUserDailyLimits = async (row: AdminRow) => {
  error.value = ''
  notice.value = ''
  try {
    await apiRequest(`/admin/users/${row.id}`, {
      method: 'PATCH',
      body: JSON.stringify({
        daily_chat_limit: row.dailyChatLimit,
        daily_image_limit: row.dailyImageLimit,
        daily_video_limit: row.dailyVideoLimit,
      }),
    })
    notice.value = `已保存 ${row.username || '用户'} 的每日调用上限`
    await load()
  } catch (e) {
    error.value = e instanceof Error ? e.message : '保存每日调用上限失败'
  }
}
const toggleUser = async (row: AdminRow) => {
  error.value = ''
  try {
    await apiRequest(`/admin/users/${row.id}`, {
      method: 'PATCH',
      body: JSON.stringify({ status: row.status === 'active' ? 'disabled' : 'active' }),
    })
    await load()
  } catch (e) {
    error.value = e instanceof Error ? e.message : '操作失败'
  }
}
const adminRoleCode = (row: AdminRow) =>
  row.adminRoleCodes?.includes('super_admin')
    ? 'super_admin'
    : row.adminRoleCodes?.includes('ass_admin')
      ? 'ass_admin'
      : 'none'
const saveAdminRole = async (row: AdminRow, event: Event) => {
  const adminRoleCode = (event.target as HTMLSelectElement).value
  error.value = ''
  try {
    await apiRequest(`/admin/users/${row.id}/admin-role`, {
      method: 'PUT',
      body: JSON.stringify({ admin_role_code: adminRoleCode }),
    })
    notice.value = `已更新 ${row.username || '用户'} 的后台角色`
    await load()
  } catch (e) {
    error.value = e instanceof Error ? e.message : '后台角色更新失败'
    await load()
  }
}
const columns = computed(() =>
  rows.value.length
    ? Object.keys(rows.value[0]).filter(
        (k) =>
          ![
            'capabilities',
            'traceback',
            'requestPayload',
            'stale',
            'mustChangePassword',
            'dailyChatLimit',
            'dailyImageLimit',
            'dailyVideoLimit',
            'adminRoleCodes',
            'permissions',
            'isSuperAdmin',
          ].includes(k),
      )
    : [],
)
onMounted(load)
</script>
<template>
  <div class="console">
    <AdminSideNav :groups="NAV_GROUPS" :active="tab" @select="select" />
    <div class="admin-workspace">
      <AdminTopBar
        :group-title="groupTitle"
        :title="tabTitle"
        :loading="loading"
        @refresh="tab === 'perf' ? loadPerf() : load()"
      />
      <main>
        <p v-if="error" class="error">{{ error }}</p>
        <p v-if="notice" class="notice">{{ notice }}</p>
        <p v-if="loading">加载中…</p>
        <section v-else-if="tab === 'dashboard' && data" class="cards">
          <article>
            <b>{{ data.users }}</b
            ><span>用户</span>
          </article>
          <article>
            <b>{{ data.projects }}</b
            ><span>项目</span>
          </article>
          <article>
            <b>{{ data.jobs }}</b
            ><span>生成任务</span>
          </article>
          <article>
            <b>{{ data.systemHumans }}</b
            ><span>系统人物</span>
          </article>
          <article>
            <b>{{ data.errors }}</b
            ><span>错误记录</span>
          </article>
          <article>
            <b>{{ data.usage?.totalTokens || 0 }}</b
            ><span>累计 Token</span>
          </article>
          <article class="wide">
            <h3>任务状态</h3>
            <pre>{{ JSON.stringify(data.jobStatuses, null, 2) }}</pre>
          </article>
          <article class="wide">
            <h3>Token 构成</h3>
            <p>
              输入 {{ data.usage?.inputTokens || 0 }} / 输出 {{ data.usage?.outputTokens || 0 }}
            </p>
          </article>
        </section>
        <template v-else>
          <AdminPromptsPanel v-if="tab === 'prompts'" :reload-token="promptsReloadToken" />
          <AdminStoryboardOptionsPanel v-if="tab === 'categories'" />
          <AdminSongEmotionProfilesPanel v-if="tab === 'song-emotions'" />
          <AdminRunningHubPanel v-if="tab === 'runninghub'" />
          <AdminKlingPanel v-if="tab === 'kling'" />
          <AdminModelComparisonPanel v-if="tab === 'chat-comparison'" />
          <AdminServerMonitoringPanel v-if="tab === 'server'" />
          <!-- 性能页：后端全量耗时（慢请求 TOP + 路径聚合） + 本浏览器会话观测 -->
          <div v-if="tab === 'perf'" class="perf">
            <section class="perf-group">
              <h3>后端 · 慢请求 TOP（≥1000ms，按耗时倒序）</h3>
              <div class="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>方法</th>
                      <th>路径</th>
                      <th>状态</th>
                      <th>耗时</th>
                      <th>时间</th>
                      <th>操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="row in backendSlow" :key="row.id">
                      <td>{{ row.method }}</td>
                      <td class="path">{{ row.path }}</td>
                      <td>{{ row.statusCode }}</td>
                      <td>
                        <span :class="{ slow: row.durationMs >= 1000 }"
                          >{{ row.durationMs }}ms</span
                        >
                      </td>
                      <td class="muted">{{ row.createdAt }}</td>
                      <td><button class="action" @click="openReqDetail(row)">详情</button></td>
                    </tr>
                  </tbody>
                </table>
                <p v-if="!backendSlow.length" class="empty">暂无慢请求（轮询/SSE 已自动排除）</p>
              </div>
            </section>
            <section class="perf-group">
              <h3>后端 · 接口耗时聚合（24h 正式流量 · max 倒序 TOP30）</h3>
              <div class="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>方法</th>
                      <th>路径</th>
                      <th>次数</th>
                      <th>平均</th>
                      <th>P95</th>
                      <th>最大</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="row in backendSummary" :key="`${row.method} ${row.path}`">
                      <td>{{ row.method }}</td>
                      <td class="path">{{ row.path }}</td>
                      <td>{{ row.count }}</td>
                      <td>{{ row.avgMs }}ms</td>
                      <td>
                        <span :class="{ slow: row.p95Ms >= 1000 }">{{ row.p95Ms }}ms</span>
                      </td>
                      <td>
                        <span :class="{ slow: row.maxMs >= 1000 }">{{ row.maxMs }}ms</span>
                      </td>
                    </tr>
                  </tbody>
                </table>
                <p v-if="!backendSummary.length" class="empty">暂无正式流量数据</p>
              </div>
            </section>
            <section class="perf-group">
              <h3>本浏览器会话 · API 耗时聚合</h3>
              <div class="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>方法</th>
                      <th>路径</th>
                      <th>次数</th>
                      <th>平均</th>
                      <th>P95</th>
                      <th>最大</th>
                      <th>解析均耗</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="row in frontPerf.apiSummary" :key="`${row.method} ${row.path}`">
                      <td>{{ row.method }}</td>
                      <td class="path">{{ row.path }}</td>
                      <td>{{ row.count }}</td>
                      <td>{{ row.avgMs }}ms</td>
                      <td>
                        <span :class="{ slow: row.p95Ms >= 800 }">{{ row.p95Ms }}ms</span>
                      </td>
                      <td>
                        <span :class="{ slow: row.maxMs >= 800 }">{{ row.maxMs }}ms</span>
                      </td>
                      <td>{{ row.parseAvgMs }}ms</td>
                    </tr>
                  </tbody>
                </table>
                <p v-if="!frontPerf.apiSummary.length" class="empty">本会话暂无 API 请求</p>
              </div>
            </section>
            <section class="perf-group">
              <h3>本浏览器会话 · 主线程长任务（>50ms 即渲染/脚本卡顿）</h3>
              <div class="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>耗时</th>
                      <th>来源</th>
                      <th>时间</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="task in frontPerf.longTasks" :key="task.id">
                      <td>
                        <span :class="{ slow: task.durationMs >= 200 }"
                          >{{ task.durationMs }}ms</span
                        >
                      </td>
                      <td class="path">{{ task.target || '-' }}</td>
                      <td class="muted">{{ new Date(task.at).toLocaleTimeString() }}</td>
                    </tr>
                  </tbody>
                </table>
                <p v-if="!frontPerf.longTasks.length" class="empty">本会话未捕获主线程长任务</p>
              </div>
            </section>
            <section v-if="frontPerf.navigation" class="perf-group">
              <h3>本浏览器会话 · 整页加载计时</h3>
              <p class="nav-timing">
                TTFB <b>{{ frontPerf.navigation.ttfbMs }}ms</b> · DOMContentLoaded
                <b>{{ frontPerf.navigation.domContentLoadedMs }}ms</b> · Load
                <b>{{ frontPerf.navigation.loadMs }}ms</b>
              </p>
            </section>
            <section v-if="frontPerf.slowApi.length" class="perf-group">
              <h3>本浏览器会话 · 最近慢请求（≥800ms）</h3>
              <div class="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>方法</th>
                      <th>路径</th>
                      <th>状态</th>
                      <th>耗时</th>
                      <th>网络</th>
                      <th>解析</th>
                      <th>重试</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="row in frontPerf.slowApi" :key="row.id">
                      <td>{{ row.method }}</td>
                      <td class="path">{{ row.path }}</td>
                      <td>{{ row.status }}</td>
                      <td>
                        <span class="slow">{{ row.totalMs }}ms</span>
                      </td>
                      <td>{{ row.networkMs }}ms</td>
                      <td>{{ row.parseMs }}ms</td>
                      <td>{{ row.retried ? '是' : '否' }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </section>
            <p class="perf-tip">
              定位链：后端 P95/max 大 → 接口/数据库/上游慢；本会话网络耗时大而后端正常 → 网络/网关；
              解析耗时长 → 响应体大；长任务集中在渲染期 → 前端渲染问题（大数据列表/图片解码）。
            </p>
          </div>
          <div v-if="tab === 'jobs'" class="filters">
            <select v-model="jobFilters.kind" @change="searchJobs">
              <option value="">全部类型</option>
              <option value="image">图片</option>
              <option value="video">视频</option>
            </select>
            <select v-model="jobFilters.status" @change="searchJobs">
              <option value="">全部状态</option>
              <option value="queued">queued</option>
              <option value="running">running</option>
              <option value="succeeded">succeeded</option>
              <option value="failed">failed</option>
              <option value="cancelled">cancelled</option>
            </select>
            <input
              v-model="jobFilters.q"
              placeholder="任务ID / 供应商任务ID"
              @keyup.enter="searchJobs"
            />
            <button class="refresh" @click="searchJobs">查询</button>
            <span class="pager">
              <button class="action" :disabled="jobPage <= 1" @click="turnJobPage(-1)">
                上一页
              </button>
              第 {{ jobPage }} 页 · 共 {{ data?.total || 0 }} 条
              <button
                class="action"
                :disabled="jobPage * jobPageSize >= (data?.total || 0)"
                @click="turnJobPage(1)"
              >
                下一页
              </button>
            </span>
          </div>
          <div v-if="tab === 'requests'" class="filters">
            <select v-model="reqFilters.runId" @change="load">
              <option value="">全部批次</option>
              <option v-for="r in reqRuns" :key="r.runId" :value="r.runId">
                {{ r.runId }}（{{ r.requests }} 次 · 均 {{ r.avgMs }}ms · 峰 {{ r.maxMs }}ms · 错
                {{ r.errors }}）
              </option>
            </select>
            <input
              v-model="reqFilters.path"
              placeholder="路径过滤 如 /api/auth"
              @keyup.enter="load"
            />
            <button class="refresh" @click="load">查询</button>
          </div>
          <div v-if="tab === 'llm'" class="filters">
            <input v-model="llmFilters.projectTaskId" placeholder="projectTaskId 过滤" />
            <input v-model="llmFilters.operation" placeholder="operation 如 ass_scene_plan" />
            <select v-model="llmFilters.status">
              <option value="">全部状态</option>
              <option value="ok">ok</option>
              <option value="error">error</option>
            </select>
            <button class="refresh" @click="load">查询</button>
          </div>
          <form v-if="tab === 'users'" class="filters" @submit.prevent="createUser">
            <input v-model="userForm.username" placeholder="用户名" required minlength="3" />
            <input v-model="userForm.displayName" placeholder="显示名称" />
            <input
              v-model="userForm.password"
              type="password"
              placeholder="初始密码（至少 8 位）"
              required
              minlength="8"
            />
            <label class="quota-field"
              >Chat/日<input v-model.number="userForm.dailyChatLimit" type="number" min="1"
            /></label>
            <label class="quota-field"
              >图片/日<input v-model.number="userForm.dailyImageLimit" type="number" min="1"
            /></label>
            <label class="quota-field"
              >视频/日<input v-model.number="userForm.dailyVideoLimit" type="number" min="1"
            /></label>
            <button class="refresh" type="submit">创建用户</button>
          </form>
          <div v-if="isPagedTab" class="pager-bar">
            <span class="pager">
              <button class="action" :disabled="currentPage <= 1" @click="turnPage(-1)">
                上一页
              </button>
              第 {{ currentPage }} 页 · 共 {{ data?.total || 0 }} 条 · 每页 {{ pageSize }} 条
              <button class="action" :disabled="currentPage >= pageCount" @click="turnPage(1)">
                下一页
              </button>
            </span>
          </div>
          <section
            v-if="
              ![
                'perf',
                'prompts',
                'categories',
                'song-emotions',
                'runninghub',
                'kling',
                'chat-comparison',
                'server',
              ].includes(tab)
            "
            class="table-wrap"
          >
            <table>
              <thead>
                <tr>
                  <th v-for="c in columns" :key="c">{{ c }}</th>
                  <th
                    v-if="
                      tab === 'models' ||
                      tab === 'llm' ||
                      tab === 'requests' ||
                      tab === 'jobs' ||
                      tab === 'users'
                    "
                  >
                    操作
                  </th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in rows" :key="row.id || row.model">
                  <td v-for="c in columns" :key="c">
                    <span
                      :class="{
                        status: c === 'status',
                        slow: tab === 'requests' && c === 'durationMs' && Number(row[c]) >= 1000,
                      }"
                      >{{ typeof row[c] === 'object' ? JSON.stringify(row[c]) : row[c] }}</span
                    ><span v-if="c === 'status' && row.stale" class="stale-flag">（疑似中断）</span>
                  </td>
                  <td v-if="tab === 'models'">
                    <button class="action" @click="toggleModel(row)">
                      {{ row.status === 'active' ? '停用' : '启用' }}
                    </button>
                  </td>
                  <td v-if="tab === 'llm'">
                    <button class="action" @click="openLlmDetail(row)">详情</button>
                  </td>
                  <td v-if="tab === 'requests'">
                    <button class="action" @click="openReqDetail(row)">详情</button>
                  </td>
                  <td v-if="tab === 'jobs'">
                    <button
                      v-if="row.providerTaskId"
                      class="action"
                      :disabled="syncing === row.id"
                      @click="syncJob(row)"
                    >
                      {{ syncing === row.id ? '同步中…' : '同步' }}
                    </button>
                  </td>
                  <td v-if="tab === 'users'">
                    <label class="admin-role-editor"
                      >后台角色
                      <select :value="adminRoleCode(row)" @change="saveAdminRole(row, $event)">
                        <option value="none">普通用户</option>
                        <option value="ass_admin">内容配置管理员</option>
                        <option value="super_admin">超级管理员</option>
                      </select>
                    </label>
                    <div class="user-quota-editor">
                      <label
                        >Chat/日<input v-model.number="row.dailyChatLimit" type="number" min="1"
                      /></label>
                      <label
                        >图片/日<input v-model.number="row.dailyImageLimit" type="number" min="1"
                      /></label>
                      <label
                        >视频/日<input v-model.number="row.dailyVideoLimit" type="number" min="1"
                      /></label>
                      <button class="action" @click="saveUserDailyLimits(row)">保存日限额</button>
                    </div>
                    <button class="action" @click="toggleUser(row)">
                      {{ row.status === 'active' ? '禁用' : '启用' }}
                    </button>
                  </td>
                </tr>
              </tbody>
            </table>
            <p v-if="!rows.length" class="empty">暂无数据</p>
          </section>
        </template>
      </main>
    </div>
    <BaseModal
      :open="!!reqDetail || (detailLoading && tab === 'requests')"
      title="请求详情"
      width="960px"
      @close="reqDetail = null"
    >
      <div class="detail-body">
        <p v-if="detailLoading">加载中…</p>
        <template v-else-if="reqDetail">
          <p class="meta">
            {{ reqDetail.method }} {{ reqDetail.path }} · {{ reqDetail.statusCode }} · 耗时
            {{ reqDetail.durationMs }}ms · {{ reqDetail.createdAt }}
          </p>
          <p class="meta">
            runId: {{ reqDetail.runId || '-' }}
            <template v-if="reqDetail.queryString"> · query: {{ reqDetail.queryString }}</template>
          </p>
          <h3>输入参数</h3>
          <pre class="payload">{{ JSON.stringify(reqDetail.requestPayload, null, 2) }}</pre>
          <h3>输出</h3>
          <pre class="payload">{{ JSON.stringify(reqDetail.responseBody, null, 2) }}</pre>
        </template>
      </div>
    </BaseModal>
    <BaseModal
      :open="!!llmDetail || (detailLoading && tab === 'llm')"
      title="LLM 调用详情"
      width="960px"
      @close="llmDetail = null"
    >
      <div class="detail-body">
        <p v-if="detailLoading">加载中…</p>
        <template v-else-if="llmDetail">
          <p class="meta">
            {{ llmDetail.operation }} · {{ llmDetail.model }} · {{ llmDetail.status }} · 耗时
            {{ (llmDetail.durationMs / 1000).toFixed(1) }}s · token 入 {{ llmDetail.inputTokens }} /
            出 {{ llmDetail.outputTokens }} / 缓存 {{ llmDetail.cachedInputTokens }}
          </p>
          <p class="meta">
            requestId: {{ llmDetail.requestId || '-' }} · {{ llmDetail.createdAt }}
          </p>
          <p v-if="llmDetail.error" class="error">{{ llmDetail.error }}</p>
          <h3>请求消息（{{ llmDetail.requestMessages?.length || 0 }} 条）</h3>
          <pre v-for="(m, i) in llmDetail.requestMessages || []" :key="i" class="payload">
[{{ m.role }}] {{ m.content }}</pre>
          <h3>模型返回原文</h3>
          <pre class="payload">{{ llmDetail.responseText || '（空）' }}</pre>
        </template>
      </div>
    </BaseModal>
  </div>
</template>
<style scoped>
.console {
  --admin-bg: #f5f7fa;
  --admin-surface: #fff;
  --admin-border: #e4e7ec;
  height: 100%;
  min-height: 0;
  background: var(--admin-bg);
  display: grid;
  grid-template-columns: 236px 1fr;
  color: var(--text);
  overflow: hidden;
}
.admin-workspace {
  display: flex;
  min-width: 0;
  min-height: 0;
  flex-direction: column;
  overflow: hidden;
}
main {
  min-width: 0;
  min-height: 0;
  flex: 1;
  overflow: auto;
  padding: 24px 30px 40px;
}
.action {
  border: 0;
  border-radius: var(--radius-sm);
  background: var(--primary);
  color: #fff;
  padding: 7px 14px;
  font-size: 13px;
  cursor: pointer;
  transition: background 0.15s;
}
.action:hover:not(:disabled) {
  background: var(--primary-hover);
}
.cards {
  display: grid;
  grid-template-columns: repeat(3, minmax(160px, 1fr));
  gap: 16px;
}
.cards article {
  background: var(--admin-surface);
  border: 1px solid var(--admin-border);
  border-radius: 8px;
  padding: 20px 22px;
  display: flex;
  flex-direction: column;
  box-shadow: var(--shadow-card);
}
.cards b {
  font-size: 30px;
  color: var(--primary);
}
.cards span {
  color: var(--text-secondary);
  margin-top: 8px;
}
.cards .wide {
  grid-column: span 3;
}
.table-wrap {
  overflow: auto;
  background: var(--admin-surface);
  border: 1px solid var(--admin-border);
  border-radius: 8px;
  box-shadow: var(--shadow-card);
}
table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
th,
td {
  padding: 11px 14px;
  border-bottom: 1px solid var(--border);
  text-align: left;
  white-space: nowrap;
  max-width: 340px;
  overflow: hidden;
  text-overflow: ellipsis;
}
th {
  background: var(--surface-muted);
  color: var(--text-secondary);
  font-size: var(--font-sm);
  font-weight: 600;
}
tbody tr:hover {
  background: var(--surface-muted);
}
.status {
  padding: 3px 8px;
  background: var(--success-light);
  color: var(--success);
  border-radius: var(--radius-sm);
  font-size: var(--font-sm);
}
.slow {
  color: var(--warning);
  font-weight: 600;
}
.empty {
  padding: 28px;
  color: var(--text-secondary);
  text-align: center;
}
.error {
  padding: 10px 14px;
  background: var(--danger-light);
  border-radius: var(--radius-sm);
  color: var(--danger);
  font-size: 13px;
}
.notice {
  padding: 10px 14px;
  background: var(--success-light);
  border-radius: var(--radius-sm);
  color: var(--success);
  font-size: 13px;
}
.stale-flag {
  color: var(--warning);
  font-weight: 600;
}
.pager {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: var(--text-secondary);
  font-size: 13px;
}
.action:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.filters {
  display: flex;
  gap: 10px;
  margin-bottom: 14px;
}
.quota-field,
.user-quota-editor label {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  color: var(--text-secondary);
  font-size: 12px;
}
.filters .quota-field input,
.user-quota-editor input {
  width: 76px;
  min-width: 0;
}
td:last-child {
  max-width: none;
  overflow: visible;
}
.user-quota-editor {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  margin-right: 8px;
}
.pager-bar {
  display: flex;
  justify-content: flex-end;
  margin-bottom: 10px;
}
/* ---------- 性能页 ---------- */
.perf {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.perf-group {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.perf-group h3 {
  margin: 0;
  font-size: 14px;
  color: var(--text);
}
.path {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 12px;
  max-width: 480px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.muted {
  color: var(--text-secondary);
  font-size: 12px;
}
.nav-timing {
  padding: 10px 14px;
  background: var(--surface-muted);
  border-radius: var(--radius-sm);
  font-size: 13px;
}
.nav-timing b {
  color: var(--primary);
}
.perf-tip {
  margin: 0;
  padding: 10px 14px;
  border-left: 3px solid var(--primary);
  background: var(--surface-muted);
  color: var(--text-secondary);
  font-size: 12px;
  line-height: 1.7;
}
.filters input,
.filters select {
  padding: 8px 12px;
  border: 1px solid var(--border-dark);
  border-radius: var(--radius-sm);
  font-size: 13px;
  min-width: 200px;
}
.filters input:focus,
.filters select:focus {
  outline: none;
  border-color: var(--primary);
}
.detail-body {
  overflow: auto;
  padding: 20px 22px;
}
.detail-body h3 {
  margin: 18px 0 8px;
  font-size: 14px;
}
.meta {
  color: var(--text-secondary);
  font-size: 13px;
  margin: 4px 0;
}
.payload {
  background: var(--surface-muted);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 12px;
  font-size: 12px;
  white-space: pre-wrap;
  word-break: break-all;
  margin: 8px 0;
}
@media (max-width: 900px) {
  .console {
    grid-template-columns: 190px 1fr;
  }
  main {
    padding: 20px 18px 32px;
  }
}
@media (max-width: 640px) {
  .console {
    grid-template-columns: 1fr;
    grid-template-rows: auto minmax(0, 1fr);
  }
  .cards {
    grid-template-columns: 1fr;
  }
  .cards .wide {
    grid-column: auto;
  }
}
</style>
