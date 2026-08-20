<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import {
  dryRunServerMaintenance,
  fetchServerMonitoring,
  type ServerMonitoringSummary,
} from '../api/adminServerMonitoring'

const data = ref<ServerMonitoringSummary | null>(null)
const loading = ref(false)
const error = ref('')
const hours = ref(24)
const maintenanceBusy = ref('')
let timer: ReturnType<typeof setInterval> | null = null

const load = async () => {
  loading.value = true
  error.value = ''
  try {
    data.value = await fetchServerMonitoring(hours.value)
  } catch (e) {
    error.value = e instanceof Error ? e.message : '监控数据加载失败'
  } finally {
    loading.value = false
  }
}
const runDry = async (action: string) => {
  maintenanceBusy.value = action
  try {
    await dryRunServerMaintenance(action)
    await load()
  } catch (e) {
    error.value = e instanceof Error ? e.message : '分析失败'
  } finally {
    maintenanceBusy.value = ''
  }
}
onMounted(() => {
  void load()
  timer = setInterval(() => void load(), 30_000)
})
onBeforeUnmount(() => timer && clearInterval(timer))

const bytes = (value = 0) => {
  const units = ['B', 'KiB', 'MiB', 'GiB', 'TiB']
  let size = value
  let index = 0
  while (size >= 1024 && index < units.length - 1) {
    size /= 1024
    index += 1
  }
  return `${size.toFixed(index >= 3 ? 2 : 1)} ${units[index]}`
}
const mbps = (value = 0) => `${((value * 8) / 1_000_000).toFixed(2)} Mbps`
const seconds = (value = 0) =>
  value >= 60 ? `${(value / 60).toFixed(1)} 分` : `${value.toFixed(0)} 秒`
const latest = computed(() => data.value?.latest)
const workload = computed(
  () =>
    latest.value?.workloads ?? {
      queues: [],
      completedLastHour: [],
      llmLastHour: { calls: 0, failed: 0, tokens: 0, avgMs: 0, p95Ms: 0 },
      configuredExecutionLimits: {},
    },
)
const workloadRows = computed(() => {
  const kinds = new Set([
    ...workload.value.queues.map((item) => item.kind),
    ...workload.value.completedLastHour.map((item) => item.kind),
  ])
  return [...kinds].sort().map(
    (kind) =>
      workload.value.queues.find((item) => item.kind === kind) ?? {
        kind,
        queued: 0,
        running: 0,
        oldestQueuedSeconds: 0,
      },
  )
})
const activeAlerts = computed(
  () => data.value?.alerts.filter((item) => item.status === 'active') ?? [],
)

const graphPoints = (field: 'cpu' | 'memory' | 'disk' | 'network') => {
  const rows = data.value?.points ?? []
  if (!rows.length) return ''
  const values = rows.map((item) => {
    if (field === 'cpu') return item.cpuPercent
    if (field === 'memory') return item.memoryUsedPercent
    if (field === 'disk') return item.diskUsedPercent
    return Math.max(item.networkTxBps, item.networkRxBps)
  })
  const max = field === 'network' ? Math.max(1, ...values) : 100
  return values
    .map(
      (value, index) =>
        `${(index / Math.max(1, values.length - 1)) * 100},${40 - (value / max) * 38}`,
    )
    .join(' ')
}

const cardTone = (value: number, warning: number, critical: number) =>
  value >= critical ? 'critical' : value >= warning ? 'warning' : 'healthy'

const changeRange = () => void load()
</script>

<template>
  <div class="monitor-panel">
    <div class="monitor-toolbar">
      <div>
        <h2>服务器资源监控</h2>
        <p>
          宿主机每 30 秒采样 · 队列与模型负载按采样时点聚合 · 月流量仅统计公网出站 · 自然月 300 GiB
        </p>
      </div>
      <div class="range-actions">
        <select v-model.number="hours" @change="changeRange">
          <option :value="1">最近 1 小时</option>
          <option :value="6">最近 6 小时</option>
          <option :value="24">最近 24 小时</option>
          <option :value="168">最近 7 天</option>
          <option :value="720">最近 30 天</option>
        </select>
        <button type="button" :disabled="loading" @click="load">
          {{ loading ? '刷新中…' : '刷新' }}
        </button>
      </div>
    </div>
    <p v-if="error" class="monitor-error">{{ error }}</p>
    <div v-if="!latest" class="empty-state">等待宿主机采集器上报第一条数据…</div>
    <template v-else>
      <p v-if="data?.stale" class="stale-warning">
        数据已超过 5 分钟未更新，请检查宿主机采集任务。
      </p>
      <section class="metric-grid">
        <article :class="cardTone(latest.cpuPercent, 80, 95)">
          <span>CPU</span><b>{{ latest.cpuPercent.toFixed(1) }}%</b>
          <small>负载 {{ latest.load.map((x) => x.toFixed(2)).join(' / ') }}</small>
          <svg viewBox="0 0 100 40" preserveAspectRatio="none">
            <polyline :points="graphPoints('cpu')" />
          </svg>
        </article>
        <article :class="cardTone(latest.memoryUsedPercent, 80, 90)">
          <span>内存</span><b>{{ latest.memoryUsedPercent.toFixed(1) }}%</b>
          <small
            >可用 {{ bytes(latest.memoryAvailableBytes) }} /
            {{ bytes(latest.memoryTotalBytes) }}</small
          >
          <svg viewBox="0 0 100 40" preserveAspectRatio="none">
            <polyline :points="graphPoints('memory')" />
          </svg>
        </article>
        <article :class="cardTone(latest.diskUsedPercent, 75, 90)">
          <span>磁盘</span><b>{{ latest.diskUsedPercent.toFixed(1) }}%</b>
          <small
            >可用 {{ bytes(latest.diskAvailableBytes) }} / {{ bytes(latest.diskTotalBytes) }}</small
          >
          <svg viewBox="0 0 100 40" preserveAspectRatio="none">
            <polyline :points="graphPoints('disk')" />
          </svg>
        </article>
        <article class="healthy">
          <span>实时带宽 · {{ latest.interface }}</span
          ><b>{{ mbps(latest.networkTxBps) }}</b>
          <small
            >出站 ↑ {{ mbps(latest.networkTxBps) }} · 入站 ↓ {{ mbps(latest.networkRxBps) }}</small
          >
          <svg viewBox="0 0 100 40" preserveAspectRatio="none">
            <polyline :points="graphPoints('network')" />
          </svg>
        </article>
      </section>

      <section class="metric-grid operational-grid">
        <article :class="cardTone(latest.cpuIowaitPercent ?? 0, 15, 30)">
          <span>CPU I/O 等待</span><b>{{ (latest.cpuIowaitPercent ?? 0).toFixed(1) }}%</b>
          <small>持续超过 15% 表示磁盘正在拖慢任务</small>
        </article>
        <article
          :class="
            cardTone(
              latest.swapTotalBytes
                ? (((latest.swapTotalBytes ?? 0) - (latest.swapFreeBytes ?? 0)) /
                    latest.swapTotalBytes) *
                    100
                : 0,
              50,
              80,
            )
          "
        >
          <span>Swap</span
          ><b>{{ bytes((latest.swapTotalBytes ?? 0) - (latest.swapFreeBytes ?? 0)) }}</b>
          <small>总计 {{ bytes(latest.swapTotalBytes ?? 0) }}</small>
        </article>
        <article class="healthy">
          <span>磁盘吞吐</span><b>写 {{ bytes(latest.diskWriteBps ?? 0) }}/s</b>
          <small
            >读 {{ bytes(latest.diskReadBps ?? 0) }}/s ·
            {{ (latest.diskReadIops ?? 0).toFixed(1) }}/{{
              (latest.diskWriteIops ?? 0).toFixed(1)
            }}
            IOPS</small
          >
        </article>
        <article class="healthy">
          <span>LLM · 最近 1 小时</span><b>{{ workload.llmLastHour.calls }} 次</b>
          <small
            >P95 {{ seconds(workload.llmLastHour.p95Ms / 1000) }} ·
            {{ workload.llmLastHour.tokens }} tokens</small
          >
        </article>
      </section>

      <section class="monitor-card">
        <div class="section-head">
          <h3>任务队列与吞吐</h3>
          <span>提交量 ≠ 同时执行量</span>
        </div>
        <div class="table-scroll">
          <table>
            <thead>
              <tr>
                <th>任务类型</th>
                <th>排队</th>
                <th>运行</th>
                <th>最久等待</th>
                <th>近 1h 成功/失败</th>
                <th>排队 P95</th>
                <th>执行 P95</th>
                <th>端到端 P95</th>
                <th>确认覆盖</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in workloadRows" :key="item.kind">
                <td>{{ item.kind }}</td>
                <td>{{ item.queued }}</td>
                <td>{{ item.running }}</td>
                <td>{{ seconds(item.oldestQueuedSeconds) }}</td>
                <td>
                  {{ workload.completedLastHour.find((x) => x.kind === item.kind)?.success ?? 0 }} /
                  {{ workload.completedLastHour.find((x) => x.kind === item.kind)?.failed ?? 0 }}
                </td>
                <td>
                  {{
                    seconds(
                      workload.completedLastHour.find((x) => x.kind === item.kind)
                        ?.queue_wait_seconds.p95 ?? 0,
                    )
                  }}
                </td>
                <td>
                  {{
                    seconds(
                      workload.completedLastHour.find((x) => x.kind === item.kind)
                        ?.execution_seconds.p95 ?? 0,
                    )
                  }}
                </td>
                <td>
                  {{
                    seconds(
                      workload.completedLastHour.find((x) => x.kind === item.kind)
                        ?.end_to_end_seconds.p95 ?? 0,
                    )
                  }}
                </td>
                <td>
                  {{
                    (
                      workload.completedLastHour.find((x) => x.kind === item.kind)
                        ?.observationCoveragePercent ?? 0
                    ).toFixed(0)
                  }}%
                </td>
              </tr>
              <tr v-if="!workloadRows.length">
                <td colspan="9">当前无排队或运行任务</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div class="capacity-list">
          <span v-for="(limit, name) in workload.configuredExecutionLimits" :key="name"
            ><b>{{ name }}</b> {{ limit }} 槽</span
          >
        </div>
      </section>

      <section class="monitor-card">
        <div class="section-head">
          <h3>Worker 实例与排空状态</h3>
          <span>进程心跳超过两倍租约未更新时标记离线</span>
        </div>
        <div class="table-scroll">
          <table>
            <thead>
              <tr>
                <th>任务类型</th>
                <th>状态</th>
                <th>在途任务</th>
                <th>版本</th>
                <th>最近心跳</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="worker in data?.workers ?? []" :key="worker.id">
                <td>{{ worker.kinds.join('、') }}</td>
                <td>
                  <span class="worker-status" :class="worker.status">{{ worker.status }}</span>
                </td>
                <td>{{ worker.activeJobs }}</td>
                <td>{{ worker.version.replace(/^git-/, '').slice(0, 7) }}</td>
                <td>{{ new Date(worker.lastHeartbeatAt).toLocaleString() }}</td>
              </tr>
              <tr v-if="!data?.workers?.length">
                <td colspan="5">暂无 Worker 注册信息</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section class="monitor-card">
        <div class="section-head">
          <h3>文件系统</h3>
          <span>同时监控容量与 inode</span>
        </div>
        <div class="table-scroll">
          <table>
            <thead>
              <tr>
                <th>挂载路径</th>
                <th>已用</th>
                <th>可用</th>
                <th>inode 已用</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="fs in latest.filesystems ?? []" :key="fs.path">
                <td>{{ fs.path }}</td>
                <td>
                  {{
                    (
                      ((fs.totalBytes - fs.availableBytes) / Math.max(1, fs.totalBytes)) *
                      100
                    ).toFixed(1)
                  }}%
                </td>
                <td>{{ bytes(fs.availableBytes) }}</td>
                <td>
                  {{
                    (((fs.inodeTotal - fs.inodeFree) / Math.max(1, fs.inodeTotal)) * 100).toFixed(
                      1,
                    )
                  }}%
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section class="monitor-card traffic-card">
        <div class="section-head">
          <h3>月度公网出站流量</h3>
          <strong>{{ data?.traffic.usedPercent.toFixed(2) }}%</strong>
        </div>
        <div class="progress">
          <i :style="{ width: `${Math.min(100, data?.traffic.usedPercent ?? 0)}%` }"></i>
        </div>
        <div class="traffic-values">
          <span
            >已用 <b>{{ bytes(data?.traffic.egressBytes) }}</b></span
          >
          <span
            >剩余 <b>{{ bytes(data?.traffic.remainingBytes) }}</b></span
          >
          <span
            >配额 <b>{{ bytes(data?.traffic.quotaBytes) }}</b></span
          >
          <span
            >周期 <b>{{ data?.traffic.month }} 自然月</b></span
          >
        </div>
      </section>

      <section class="monitor-card">
        <div class="section-head">
          <h3>容器资源</h3>
          <span>{{ latest.containers.length }} 个容器</span>
        </div>
        <div class="table-scroll">
          <table>
            <thead>
              <tr>
                <th>容器</th>
                <th>CPU</th>
                <th>内存</th>
                <th>内存用量</th>
                <th>网络 IO</th>
                <th>磁盘 IO</th>
                <th>进程数</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in latest.containers" :key="item.name">
                <td>{{ item.name }}</td>
                <td>{{ item.cpuPercent.toFixed(2) }}%</td>
                <td>{{ item.memoryPercent.toFixed(2) }}%</td>
                <td>{{ item.memoryUsage }}</td>
                <td>{{ item.networkIO }}</td>
                <td>{{ item.blockIO }}</td>
                <td>{{ item.pids ?? 0 }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section class="two-columns">
        <article class="monitor-card">
          <div class="section-head">
            <h3>告警记录</h3>
            <span>{{ activeAlerts.length }} 条活动告警</span>
          </div>
          <div v-if="!data?.alerts.length" class="compact-empty">暂无告警</div>
          <div
            v-for="alert in data?.alerts"
            :key="alert.id"
            class="alert-row"
            :class="alert.severity"
          >
            <b>{{ alert.title }}</b
            ><span>{{ alert.message }}</span
            ><small
              >{{ alert.status }} · {{ new Date(alert.lastObservedAt).toLocaleString() }}</small
            >
          </div>
        </article>
        <article class="monitor-card">
          <div class="section-head">
            <h3>安全维护分析</h3>
            <span>第一阶段仅 dry-run，不执行删除</span>
          </div>
          <div class="maintenance-actions">
            <button
              type="button"
              :disabled="!!maintenanceBusy"
              @click="runDry('cleanup_temp_files')"
            >
              分析临时文件
            </button>
            <button
              type="button"
              :disabled="!!maintenanceBusy"
              @click="runDry('cleanup_dangling_images')"
            >
              分析无用镜像
            </button>
            <button type="button" :disabled="!!maintenanceBusy" @click="runDry('rotate_logs')">
              分析日志轮转
            </button>
          </div>
          <div v-for="run in data?.maintenanceRuns" :key="run.id" class="maintenance-row">
            <b>{{ run.action }}</b
            ><span>{{ run.summary }}</span
            ><small>{{ new Date(run.createdAt).toLocaleString() }}</small>
          </div>
        </article>
      </section>
    </template>
  </div>
</template>

<style scoped>
.monitor-panel {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.monitor-toolbar,
.section-head,
.traffic-values,
.range-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.monitor-toolbar h2,
.section-head h3 {
  margin: 0;
}
.monitor-toolbar p {
  margin: 4px 0 0;
  color: #667085;
  font-size: 12px;
}
.range-actions select,
.range-actions button,
.maintenance-actions button {
  height: 34px;
  border: 1px solid #d0d5dd;
  border-radius: 7px;
  background: #fff;
  padding: 0 12px;
  color: #344054;
}
.metric-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}
.operational-grid article {
  min-height: 106px;
}
.capacity-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 16px;
  margin-top: 12px;
  color: #667085;
  font-size: 12px;
}
.worker-status {
  color: var(--success);
  font-weight: 650;
}
.worker-status.draining {
  color: var(--warning);
}
.worker-status.drained,
.worker-status.offline {
  color: var(--danger);
}
.metric-grid article,
.monitor-card {
  border: 1px solid #e4e7ec;
  border-radius: 9px;
  background: #fff;
  padding: 16px;
  box-shadow: 0 1px 2px rgba(16, 24, 40, 0.03);
}
.metric-grid article {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 5px;
  border-top: 3px solid #12b76a;
}
.metric-grid article.warning {
  border-top-color: #f79009;
}
.metric-grid article.critical {
  border-top-color: #f04438;
}
.metric-grid span,
.section-head span {
  color: #667085;
  font-size: 12px;
}
.metric-grid b {
  font-size: 25px;
  color: #1d2939;
}
.metric-grid small {
  overflow: hidden;
  color: #667085;
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.metric-grid svg {
  width: 100%;
  height: 40px;
  margin-top: 7px;
}
.metric-grid polyline {
  fill: none;
  stroke: var(--primary);
  stroke-width: 1.6;
  vector-effect: non-scaling-stroke;
}
.progress {
  height: 10px;
  margin: 15px 0;
  border-radius: 6px;
  background: #eaecf0;
  overflow: hidden;
}
.progress i {
  display: block;
  height: 100%;
  border-radius: 6px;
  background: linear-gradient(90deg, #12b76a, #f79009, #f04438);
}
.traffic-values {
  justify-content: flex-start;
  flex-wrap: wrap;
}
.traffic-values span {
  min-width: 150px;
  color: #667085;
  font-size: 12px;
}
.traffic-values b {
  color: #344054;
}
.table-scroll {
  overflow: auto;
  margin-top: 12px;
}
table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}
th,
td {
  padding: 9px 10px;
  border-bottom: 1px solid #eaecf0;
  text-align: left;
  white-space: nowrap;
}
th {
  color: #667085;
  background: #f9fafb;
}
.two-columns {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}
.alert-row,
.maintenance-row {
  display: grid;
  gap: 3px;
  margin-top: 10px;
  padding: 10px;
  border-left: 3px solid #f79009;
  background: #fffaeb;
}
.alert-row.critical {
  border-color: #f04438;
  background: #fef3f2;
}
.alert-row span,
.maintenance-row span {
  font-size: 12px;
  color: #475467;
}
.alert-row small,
.maintenance-row small {
  font-size: 10px;
  color: #98a2b3;
}
.maintenance-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 12px;
}
.maintenance-actions button {
  cursor: pointer;
}
.maintenance-row {
  border-left-color: #667085;
  background: #f9fafb;
}
.empty-state,
.compact-empty,
.stale-warning,
.monitor-error {
  padding: 16px;
  border: 1px dashed #d0d5dd;
  border-radius: 8px;
  color: #667085;
  background: #fff;
}
.stale-warning {
  border-color: #fec84b;
  background: #fffaeb;
  color: #b54708;
}
.monitor-error {
  border-color: #fda29b;
  background: #fef3f2;
  color: #b42318;
}
@media (max-width: 1100px) {
  .metric-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}
@media (max-width: 720px) {
  .metric-grid,
  .two-columns {
    grid-template-columns: 1fr;
  }
  .monitor-toolbar {
    align-items: flex-start;
    flex-direction: column;
  }
  .traffic-values span {
    min-width: 120px;
  }
}
</style>
