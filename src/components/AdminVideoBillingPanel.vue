<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import {
  getVideoBillingDetail,
  getVideoBilling,
  getVideoBillingReconcileJob,
  reconcileVideoBilling,
  type VideoBillingResponse,
  type VideoBillingDetail,
} from '../api/adminVideoBilling'
import AdminVideoBillingDetailModal from './AdminVideoBillingDetailModal.vue'
import AdminPagination from './base/AdminPagination.vue'
import { formatChinaDateTime } from '../utils/dateTime'
import { formatElapsedSeconds } from '../utils/duration'

const emptyData = (): VideoBillingResponse => ({
  total: 0,
  items: [],
  models: [],
  summary: {
    totalAmount: 0,
    pricedRecords: 0,
    failedRecords: 0,
    failedAmount: 0,
    excludedRecords: 0,
    unpricedRecords: 0,
    noUsageRecords: 0,
    agentTestRecords: 0,
    businessRecords: 0,
  },
})
const data = ref(emptyData())
const loading = ref(false)
const reconciling = ref(false)
const detailLoading = ref(false)
const detail = ref<VideoBillingDetail | null>(null)
const detailOpen = ref(false)
const error = ref('')
const notice = ref('')
const status = ref('')
const model = ref('')
const origin = ref('')
const keyword = ref('')
const offset = ref(0)
const pageSize = 50
const currentPage = computed(() => Math.floor(offset.value / pageSize) + 1)

const money = (value: number) => `¥${value.toFixed(6)}`
const compactNumber = (value: number, digits = 6) => Number(value.toFixed(digits)).toLocaleString()
const usage = (value: number, unit: string) =>
  unit === 'Token' ? Math.round(value).toLocaleString() : compactNumber(value)
const compactMoney = (value: number) => `¥${compactNumber(value)}`
const perSecondJiao = (amount: number, durationSeconds: number) =>
  durationSeconds > 0 && amount > 0 ? `${compactNumber((amount / durationSeconds) * 10, 4)}毛` : '-'
const billingLabel = (value: string) =>
  ({ priced: '已计费', excluded: '渠道暂不计费', unpriced: '缺少价格', no_usage: '无供应商用量' })[
    value
  ] || value

const load = async () => {
  loading.value = true
  error.value = ''
  const query = new URLSearchParams({ limit: String(pageSize), offset: String(offset.value) })
  if (status.value) query.set('status', status.value)
  if (model.value) query.set('model', model.value)
  if (origin.value) query.set('origin', origin.value)
  if (keyword.value.trim()) query.set('q', keyword.value.trim())
  try {
    data.value = await getVideoBilling(query)
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '加载失败'
  } finally {
    loading.value = false
  }
}
const search = () => {
  offset.value = 0
  void load()
}
const clearSearch = () => {
  keyword.value = ''
  offset.value = 0
  void load()
}
const selectPage = (page: number) => {
  offset.value = (page - 1) * pageSize
  void load()
}
const reconcile = async () => {
  reconciling.value = true
  notice.value = ''
  try {
    const accepted = await reconcileVideoBilling()
    notice.value = accepted.reused
      ? '已有历史核算任务正在执行，已继续跟踪'
      : '历史核算任务已进入后台队列'
    while (true) {
      const job = await getVideoBillingReconcileJob(accepted.jobId)
      if (job.status === 'succeeded') {
        const result = job.result ?? { processed: 0, failed: 0, priced: 0 }
        notice.value = `历史核算完成：${result.processed} 条，其中失败任务 ${result.failed} 条、已计费 ${result.priced} 条`
        break
      }
      if (job.status === 'failed' || job.status === 'cancelled') {
        throw new Error(job.error || '历史核算任务失败')
      }
      notice.value = `历史核算进行中：${job.progress}%`
      await new Promise((resolve) => window.setTimeout(resolve, 1000))
    }
    await load()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '历史核算失败'
  } finally {
    reconciling.value = false
  }
}
const openDetail = async (id: string) => {
  detailOpen.value = true
  detailLoading.value = true
  detail.value = null
  try {
    detail.value = await getVideoBillingDetail(id)
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '详情加载失败'
    detailOpen.value = false
  } finally {
    detailLoading.value = false
  }
}

onMounted(load)
</script>

<template>
  <section class="billing-panel">
    <div class="summary">
      <article>
        <b>{{ money(data.summary.totalAmount) }}</b
        ><span>统计费用</span>
      </article>
      <article>
        <b>{{ data.summary.pricedRecords }}</b
        ><span>已计费视频</span>
      </article>
      <article class="failed">
        <b>{{ data.summary.failedRecords }}</b
        ><span>最终失败任务</span>
      </article>
      <article class="failed">
        <b>{{ money(data.summary.failedAmount) }}</b
        ><span>失败任务费用</span>
      </article>
      <article>
        <b>{{ data.summary.excludedRecords }}</b
        ><span>RunningHub 暂不计费</span>
      </article>
      <article class="agent-test">
        <b>{{ data.summary.agentTestRecords }}</b
        ><span>Agent 开发测试</span>
      </article>
    </div>
    <div class="toolbar">
      <select v-model="status" aria-label="对账状态" @change="search">
        <option value="">全部状态</option>
        <option value="failed">最终生成失败</option>
        <option value="priced">已计费</option>
        <option value="excluded">渠道暂不计费</option>
        <option value="unpriced">缺少价格</option>
        <option value="no_usage">无供应商用量</option>
      </select>
      <select v-model="model" aria-label="视频模型" @change="search">
        <option value="">全部模型</option>
        <option v-for="item in data.models" :key="item" :value="item">{{ item }}</option>
      </select>
      <select v-model="origin" aria-label="生成来源" @change="search">
        <option value="">全部来源</option>
        <option value="business">正常业务</option>
        <option value="agent_test">Agent 开发测试</option>
      </select>
      <div class="search-field">
        <input
          v-model="keyword"
          aria-label="搜索"
          placeholder="用户、项目、子项目或工单ID"
          @keyup.enter="search"
        />
        <button
          v-if="keyword"
          type="button"
          class="clear-search"
          aria-label="清空搜索并重置列表"
          title="清空搜索"
          @click="clearSearch"
        >
          ×
        </button>
      </div>
      <button class="action search-action" @click="search">查询</button>
      <button class="action primary" :disabled="reconciling" @click="reconcile">
        {{ reconciling ? '核算中…' : '重新核算全部历史' }}
      </button>
    </div>
    <p v-if="error" class="message error">{{ error }}</p>
    <p v-if="notice" class="message notice">{{ notice }}</p>
    <AdminPagination
      :page="currentPage"
      :total="data.total"
      :page-size="pageSize"
      position="顶部"
      @change="selectPage"
    />
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>完成时间</th>
            <th>用户 / 项目</th>
            <th>模型</th>
            <th>来源</th>
            <th>时长</th>
            <th>生成耗时</th>
            <th>生成结果</th>
            <th>计费用量/单价<small>Token / 秒</small></th>
            <th>费用/每秒费用（单价毛）</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in data.items" :key="item.id" :class="{ 'failed-row': item.isFailed }">
            <td>{{ item.completedAt ? formatChinaDateTime(item.completedAt) : '-' }}</td>
            <td>
              <b>{{ item.username }}</b
              ><small>{{ item.projectName }} / {{ item.taskTitle }}</small>
            </td>
            <td>
              {{ item.model || '-'
              }}<small>
                {{ item.provider || '-' }} · {{ item.providerResolution || item.resolution }}
                <template v-if="item.actualWidth && item.actualHeight">
                  · {{ item.actualWidth }}×{{ item.actualHeight }}
                </template>
              </small>
              <span v-if="item.discountLabel" class="discount-badge">{{ item.discountLabel }}</span>
            </td>
            <td>
              <span :class="['origin-badge', { agent: item.generationOrigin === 'agent_test' }]">
                {{ item.generationOrigin === 'agent_test' ? 'Agent 开发测试' : '正常业务' }}
              </span>
              <small v-if="item.agentRunId">{{ item.agentName }} · {{ item.agentRunId }}</small>
            </td>
            <td>{{ item.durationSeconds ? `${item.durationSeconds} 秒` : '-' }}</td>
            <td>{{ formatElapsedSeconds(item.generationElapsedSeconds) }}</td>
            <td>
              <span :class="['badge', { failed: item.isFailed }]">{{
                item.isFailed ? '生成失败' : '生成成功'
              }}</span
              ><small>{{ billingLabel(item.billingStatus) }}</small>
            </td>
            <td>
              {{ usage(item.usageQuantity, item.usageUnit) }}<small>{{ item.rateLabel }}</small>
            </td>
            <td class="amount">
              {{ compactMoney(item.amount)
              }}<small>{{ perSecondJiao(item.amount, item.durationSeconds) }}</small>
            </td>
            <td><button class="action" @click="openDetail(item.id)">详情</button></td>
          </tr>
        </tbody>
      </table>
      <p v-if="loading" class="empty">加载中…</p>
      <p v-else-if="!data.items.length" class="empty">暂无对账记录</p>
    </div>
    <AdminPagination
      :page="currentPage"
      :total="data.total"
      :page-size="pageSize"
      position="底部"
      @change="selectPage"
    />
    <AdminVideoBillingDetailModal
      :open="detailOpen"
      :loading="detailLoading"
      :detail="detail"
      @close="detailOpen = false"
    />
  </section>
</template>

<style scoped src="./AdminVideoBillingPanel.css"></style>
