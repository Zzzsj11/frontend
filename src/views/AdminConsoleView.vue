<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { apiRequest } from '../api/client'
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
const tab = ref<Tab>('dashboard'),
  loading = ref(false),
  error = ref(''),
  data = ref<any>(null)
const tabs: [Tab, string][] = [
  ['dashboard', '仪表盘'],
  ['users', '用户'],
  ['projects', '项目'],
  ['jobs', '生成任务'],
  ['usage', '费用用量'],
  ['models', '模型管理'],
  ['errors', '错误日志'],
  ['audit', '操作审计'],
  ['llm', 'LLM 调用'],
  ['requests', '接口耗时'],
]
const llmFilters = ref({ projectTaskId: '', operation: '', status: '' })
const llmDetail = ref<any>(null),
  detailLoading = ref(false)
const reqFilters = ref({ runId: '', path: '' })
const reqRuns = ref<any[]>([])
const reqDetail = ref<any>(null)
const jobFilters = ref({ kind: '', status: '', q: '' })
const jobPage = ref(1)
const jobPageSize = 50
const notice = ref('')
const syncing = ref('')
const llmEndpoint = computed(() => {
  const query = new URLSearchParams()
  if (llmFilters.value.projectTaskId.trim())
    query.set('projectTaskId', llmFilters.value.projectTaskId.trim())
  if (llmFilters.value.operation.trim()) query.set('operation', llmFilters.value.operation.trim())
  if (llmFilters.value.status) query.set('status', llmFilters.value.status)
  query.set('limit', '100')
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
      projects: '/admin/projects',
      jobs: jobsEndpoint.value,
      usage: '/admin/usage',
      models: '/admin/models',
      errors: '/admin/api-errors',
      audit: '/admin/audit-logs',
      llm: llmEndpoint.value,
      requests: reqEndpoint.value,
    })[tab.value],
)
const rows = computed<any[]>(() =>
  Array.isArray(data.value) ? data.value : data.value?.items || [],
)
const load = async () => {
  loading.value = true
  error.value = ''
  try {
    data.value = await apiRequest(endpoint.value)
  } catch (e) {
    error.value = e instanceof Error ? e.message : '加载失败'
  } finally {
    loading.value = false
  }
}
const select = async (value: Tab) => {
  tab.value = value
  if (value === 'requests') void loadReqRuns()
  await load()
}
const reqEndpoint = computed(() => {
  const query = new URLSearchParams()
  if (reqFilters.value.runId) query.set('runId', reqFilters.value.runId)
  if (reqFilters.value.path.trim()) query.set('path', reqFilters.value.path.trim())
  query.set('limit', '200')
  return `/admin/request-logs?${query.toString()}`
})
const loadReqRuns = async () => {
  try {
    reqRuns.value = await apiRequest('/admin/request-logs/runs')
  } catch {
    reqRuns.value = []
  }
}
const openReqDetail = async (row: any) => {
  detailLoading.value = true
  reqDetail.value = null
  try {
    reqDetail.value = await apiRequest(`/admin/request-logs/${row.id}`)
  } catch (e) {
    error.value = e instanceof Error ? e.message : '详情加载失败'
  } finally {
    detailLoading.value = false
  }
}
const openLlmDetail = async (row: any) => {
  detailLoading.value = true
  llmDetail.value = null
  try {
    llmDetail.value = await apiRequest(`/admin/llm-calls/${row.id}`)
  } catch (e) {
    error.value = e instanceof Error ? e.message : '详情加载失败'
  } finally {
    detailLoading.value = false
  }
}
const toggleModel = async (row: any) => {
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
const syncJob = async (row: any) => {
  syncing.value = row.id
  notice.value = ''
  error.value = ''
  try {
    const result: any = await apiRequest(`/admin/jobs/${row.id}/sync`, { method: 'POST' })
    const actionText: Record<string, string> = {
      recovered: '已挽回结果并落库',
      failed: '已同步失败原因',
      resumed: '已重新挂起轮询',
      unchanged: '状态一致无需处理',
      skipped: '任务正在执行中',
    }
    notice.value = `同步完成：供应商状态 ${result.providerStatus ?? '-'} · ${actionText[result.action] || result.action}`
    await load()
  } catch (e) {
    error.value = e instanceof Error ? e.message : '同步失败'
  } finally {
    syncing.value = ''
  }
}
const columns = computed(() =>
  rows.value.length
    ? Object.keys(rows.value[0]).filter(
        (k) => !['capabilities', 'traceback', 'requestPayload', 'stale'].includes(k),
      )
    : [],
)
onMounted(load)
</script>
<template>
  <div class="console">
    <aside>
      <div class="brand">映刻 MV<br /><small>管理控制台 v0.1</small></div>
      <button
        v-for="item in tabs"
        :key="item[0]"
        :class="{ on: tab === item[0] }"
        @click="select(item[0])"
      >
        {{ item[1] }}</button
      ><RouterLink to="/projects">← 返回工作台</RouterLink>
    </aside>
    <main>
      <header>
        <div>
          <h1>{{ tabs.find((x) => x[0] === tab)?.[1] }}</h1>
          <p>MV AI 生产平台运营与模型控制中心</p>
        </div>
        <button class="refresh" @click="load">刷新</button>
      </header>
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
          <p>输入 {{ data.usage?.inputTokens || 0 }} / 输出 {{ data.usage?.outputTokens || 0 }}</p>
        </article>
      </section>
      <template v-else>
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
            <button class="action" :disabled="jobPage <= 1" @click="turnJobPage(-1)">上一页</button>
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
        <section class="table-wrap">
          <table>
            <thead>
              <tr>
                <th v-for="c in columns" :key="c">{{ c }}</th>
                <th
                  v-if="tab === 'models' || tab === 'llm' || tab === 'requests' || tab === 'jobs'"
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
                      slow: tab === 'requests' && c === 'durationMs' && row[c] >= 1000,
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
              </tr>
            </tbody>
          </table>
          <p v-if="!rows.length" class="empty">暂无数据</p>
        </section>
      </template>
    </main>
    <div
      v-if="reqDetail || (detailLoading && tab === 'requests')"
      class="overlay"
      @click.self="reqDetail = null"
    >
      <div class="detail">
        <header>
          <h2>请求详情</h2>
          <button class="action" @click="reqDetail = null">关闭</button>
        </header>
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
    </div>
    <div
      v-if="llmDetail || (detailLoading && tab === 'llm')"
      class="overlay"
      @click.self="llmDetail = null"
    >
      <div class="detail">
        <header>
          <h2>LLM 调用详情</h2>
          <button class="action" @click="llmDetail = null">关闭</button>
        </header>
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
    </div>
  </div>
</template>
<style scoped>
.console {
  min-height: 100vh;
  background: #f6f7f9;
  display: grid;
  grid-template-columns: 220px 1fr;
  color: #25262a;
}
aside {
  background: #17191d;
  color: #fff;
  padding: 24px 14px;
  display: flex;
  flex-direction: column;
  gap: 7px;
}
.brand {
  font-size: 19px;
  font-weight: 700;
  padding: 8px 10px 25px;
}
.brand small {
  font-size: 11px;
  color: #999;
  font-weight: 400;
}
aside button,
aside a {
  border: 0;
  background: transparent;
  color: #aaa;
  text-align: left;
  padding: 11px 13px;
  border-radius: var(--radius-sm);
  text-decoration: none;
  cursor: pointer;
}
aside button.on,
aside button:hover {
  background: var(--primary);
  color: #fff;
}
aside a {
  margin-top: auto;
}
main {
  padding: 30px;
  min-width: 0;
}
header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 25px;
}
h1 {
  margin: 0;
  font-size: 25px;
}
header p {
  margin: 6px 0;
  color: var(--text-secondary);
}
.refresh,
.action {
  border: 0;
  border-radius: var(--radius-sm);
  background: var(--primary);
  color: #fff;
  padding: 8px 14px;
  cursor: pointer;
}
.cards {
  display: grid;
  grid-template-columns: repeat(3, minmax(160px, 1fr));
  gap: 16px;
}
.cards article {
  background: #fff;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  padding: 22px;
  display: flex;
  flex-direction: column;
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
  background: #fff;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
}
table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
th,
td {
  padding: 12px 14px;
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
}
.status {
  padding: 3px 7px;
  background: #eef8ef;
  border-radius: var(--radius-sm);
}
.slow {
  color: #c2410c;
  font-weight: 600;
}
.empty,
.error {
  padding: 20px;
}
.error {
  color: var(--danger);
}
.notice {
  padding: 10px 14px;
  background: #eef8ef;
  border: 1px solid #b7e0bd;
  border-radius: var(--radius-sm);
  color: #166534;
  font-size: 13px;
}
.stale-flag {
  color: #c2410c;
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
.filters input,
.filters select {
  padding: 8px 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  font-size: 13px;
  min-width: 200px;
}
.overlay {
  position: fixed;
  inset: 0;
  background: rgba(15, 17, 21, 0.55);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 60;
}
.detail {
  background: #fff;
  border-radius: var(--radius-md);
  width: min(960px, 92vw);
  max-height: 86vh;
  overflow: auto;
  padding: 24px;
}
.detail header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
}
.detail h2 {
  margin: 0;
  font-size: 18px;
}
.detail h3 {
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
</style>
