<script setup lang="ts">
import { onMounted, ref } from 'vue'
import {
  getVideoBilling,
  reconcileVideoBilling,
  type VideoBillingResponse,
} from '../api/adminVideoBilling'

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
  },
})
const data = ref(emptyData())
const loading = ref(false)
const reconciling = ref(false)
const error = ref('')
const notice = ref('')
const status = ref('')
const model = ref('')
const keyword = ref('')
const offset = ref(0)
const pageSize = 50

const money = (value: number) => `¥${value.toFixed(6)}`
const usage = (value: number, unit: string) =>
  unit === 'Token' ? `${Math.round(value).toLocaleString()} Token` : `${value} ${unit || '-'}`
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
const changePage = (delta: number) => {
  offset.value = Math.max(0, offset.value + delta * pageSize)
  void load()
}
const reconcile = async () => {
  reconciling.value = true
  notice.value = ''
  try {
    const result = await reconcileVideoBilling()
    notice.value = `历史核算完成：${result.processed} 条，其中失败任务 ${result.failed} 条、已计费 ${result.priced} 条`
    await load()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '历史核算失败'
  } finally {
    reconciling.value = false
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
      <input
        v-model="keyword"
        aria-label="搜索"
        placeholder="用户、项目、子项目或工单ID"
        @keyup.enter="search"
      />
      <button class="action" @click="search">查询</button>
      <button class="action primary" :disabled="reconciling" @click="reconcile">
        {{ reconciling ? '核算中…' : '重新核算全部历史' }}
      </button>
    </div>
    <p v-if="error" class="message error">{{ error }}</p>
    <p v-if="notice" class="message notice">{{ notice }}</p>
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>完成时间</th>
            <th>用户 / 项目</th>
            <th>模型</th>
            <th>生成结果</th>
            <th>计费用量</th>
            <th>单价</th>
            <th>费用</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in data.items" :key="item.id" :class="{ 'failed-row': item.isFailed }">
            <td>{{ item.completedAt ? new Date(item.completedAt).toLocaleString() : '-' }}</td>
            <td>
              <b>{{ item.username }}</b
              ><small>{{ item.projectName }} / {{ item.taskTitle }}</small>
            </td>
            <td>
              {{ item.model || '-'
              }}<small>{{ item.provider || '-' }} · {{ item.resolution }}</small>
            </td>
            <td>
              <span :class="['badge', { failed: item.isFailed }]">{{
                item.isFailed ? '生成失败' : '生成成功'
              }}</span
              ><small>{{ billingLabel(item.billingStatus) }}</small>
            </td>
            <td>{{ usage(item.usageQuantity, item.usageUnit) }}</td>
            <td>{{ item.unitPrice ? money(item.unitPrice) : '-' }}</td>
            <td class="amount">{{ money(item.amount) }}</td>
          </tr>
        </tbody>
      </table>
      <p v-if="loading" class="empty">加载中…</p>
      <p v-else-if="!data.items.length" class="empty">暂无对账记录</p>
    </div>
    <div class="pager">
      <button :disabled="offset === 0" @click="changePage(-1)">上一页</button
      ><span>{{ offset + 1 }}–{{ Math.min(offset + pageSize, data.total) }} / {{ data.total }}</span
      ><button :disabled="offset + pageSize >= data.total" @click="changePage(1)">下一页</button>
    </div>
  </section>
</template>

<style scoped>
.billing-panel {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.summary {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 10px;
}
.summary article {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 16px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
}
.summary b {
  font-size: 20px;
}
.summary span,
small {
  color: var(--text-secondary);
  font-size: var(--font-sm);
}
.summary .failed {
  background: var(--danger-light);
  border-color: var(--danger);
}
.summary .failed b {
  color: var(--danger);
}
.toolbar {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.toolbar input,
.toolbar select,
.pager button {
  padding: 8px 10px;
  border: 1px solid var(--border-dark);
  border-radius: var(--radius-sm);
  background: var(--surface);
}
.toolbar input {
  min-width: 240px;
}
.action {
  padding: 8px 12px;
  border: 1px solid var(--border-dark);
  border-radius: var(--radius-sm);
  background: var(--surface);
  cursor: pointer;
}
.action.primary {
  background: var(--primary);
  color: var(--on-primary);
  border-color: var(--primary);
}
.table-wrap {
  overflow: auto;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
}
table {
  width: 100%;
  border-collapse: collapse;
}
th,
td {
  padding: 11px 12px;
  border-bottom: 1px solid var(--border);
  text-align: left;
  white-space: nowrap;
}
td small {
  display: block;
  margin-top: 4px;
}
.failed-row {
  background: var(--danger-light);
}
.badge {
  display: inline-block;
  padding: 3px 7px;
  border-radius: var(--radius-pill);
  background: var(--success-light);
  color: var(--success);
  font-size: var(--font-sm);
}
.badge.failed {
  background: var(--danger);
  color: var(--on-primary);
  font-weight: 600;
}
.amount {
  font-weight: 700;
}
.message,
.empty {
  padding: 12px;
  color: var(--text-secondary);
}
.message.error {
  background: var(--danger-light);
  color: var(--danger);
}
.message.notice {
  background: var(--success-light);
  color: var(--success);
}
.pager {
  display: flex;
  justify-content: flex-end;
  align-items: center;
  gap: 10px;
  color: var(--text-secondary);
}
@media (max-width: 900px) {
  .summary {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
