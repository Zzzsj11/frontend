<script setup lang="ts">
import { ref } from 'vue'
import { labels, usePortal, type Job } from '../stores/portal'
import { prettyPoints, prettySignedPoints, localDate } from '../utils/financial'
import PointsSummary from './PointsSummary.vue'
import PaginationControls from './base/PaginationControls.vue'
import JobDetail from './JobDetail.vue'
const store = usePortal()
const detail = ref<Job | null>(null)
const detailOpen = ref(false)
const detailLoading = ref(false)
const detailError = ref('')
let request = 0
async function showJob(id: string) {
  const current = ++request
  detail.value = null
  detailOpen.value = true
  detailLoading.value = true
  detailError.value = ''
  try {
    const job = await store.jobDetail(id)
    if (current === request) detail.value = job
  } catch {
    if (current === request) detailError.value = '无法加载任务详情，请关闭后重试。'
  } finally {
    if (current === request) detailLoading.value = false
  }
}
function closeDetail() {
  request++
  detailOpen.value = false
}
async function changePage(value: number) {
  store.ledgerPage = value
  await store.reload()
}
async function changeLimit(value: number) {
  store.ledgerLimit = value
  await changePage(1)
}
async function filter() {
  await changePage(1)
}
const states: Record<string, string> = {
  queued: '排队中',
  running: '处理中',
  succeeded: '已完成',
  failed: '失败',
}
</script>
<template>
  <div class="account-page">
    <PointsSummary />
    <section class="card ledger" aria-label="积分明细">
      <div class="heading">
        <div>
          <h2>积分明细</h2>
          <p class="muted">
            每个任务汇总为一条记录，点击任务 ID 查看详情；余额为对应 Key 的记账余额。
          </p>
        </div>
        <button class="secondary" :disabled="store.loading" @click="store.reload">刷新积分</button>
      </div>
      <div class="filters">
        <label
          >所属 Key<select
            v-model="store.ledgerKey"
            aria-label="筛选 Key"
            :disabled="store.loading"
            @change="filter"
          >
            <option value="">全部 Key</option>
            <option v-for="key in store.historyKeys" :key="key.id" :value="key.id">
              {{ key.name }}{{ key.deleted ? '（已删除）' : '' }}
            </option>
          </select></label
        >
        <label
          >变动类型<select
            v-model="store.ledgerKind"
            aria-label="筛选积分类型"
            :disabled="store.loading"
            @change="filter"
          >
            <option value="">全部类型</option>
            <option
              v-for="kind in [
                'generation',
                'reconciliation',
                'monthly_reset',
                'quota_adjust',
                'manual_credit',
                'manual_debit',
              ]"
              :key="kind"
              :value="kind"
            >
              {{ kind === 'generation' ? '生成任务' : labels[kind] }}
            </option>
          </select></label
        >
      </div>
      <PaginationControls
        :page="store.ledgerPage"
        :limit="store.ledgerLimit"
        :total="store.ledgerTotal"
        :loading="store.loading"
        @page="changePage"
        @limit="changeLimit"
      />
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>时间 / Key</th>
              <th>类型 / 状态</th>
              <th>说明</th>
              <th>任务 ID</th>
              <th>积分变化</th>
              <th>Key 月 / 临时余额</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in store.ledger" :key="row.row_type + row.id">
              <td>
                {{ localDate(row.created_at) }}<small>{{ row.key_name }}</small>
              </td>
              <td>
                {{
                  row.job_id
                    ? { chat: '文本生成', text: '文本生成', image: '图片生成', video: '视频生成' }[
                        row.task_kind
                      ] || '生成任务'
                    : labels[row.kind] || row.kind
                }}
                <small v-if="row.status">{{ states[row.status] || row.status }}</small>
              </td>
              <td>
                <small>{{ row.reason }}</small>
              </td>
              <td>
                <button
                  v-if="row.job_id"
                  class="link-button task-link"
                  @click="showJob(row.job_id)"
                >
                  {{ row.job_id }}</button
                ><span v-else>—</span>
              </td>
              <td
                class="number"
                :class="{ positive: Number(row.points) > 0, negative: Number(row.points) < 0 }"
              >
                {{ row.points == null ? '待结算' : prettySignedPoints(row.points) }}
                <small v-if="row.reserved_points && Number(row.reserved_points) > 0"
                  >预占 {{ prettyPoints(row.reserved_points) }}</small
                >
              </td>
              <td class="number">
                <template v-if="row.monthly_after != null"
                  >{{ prettyPoints(row.monthly_after) }} /
                  {{ prettyPoints(row.extra_after) }}</template
                ><span v-else>—</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <p v-if="!store.ledger.length" class="empty">
        {{ store.ledgerKey || store.ledgerKind ? '没有符合筛选条件的积分记录' : '暂无积分记录' }}
      </p>
    </section>
    <JobDetail
      :open="detailOpen"
      :job="detail"
      :loading="detailLoading"
      :error="detailError"
      @close="closeDetail"
    />
  </div>
</template>
<style scoped>
.account-page {
  display: grid;
  gap: 24px;
}
h2 {
  font-size: 21px;
}
.filters {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  margin-top: 16px;
}
.filters label {
  min-width: 180px;
}
small {
  display: block;
  color: var(--muted);
  font-size: 12px;
  margin-top: 8px;
  max-width: 280px;
  line-height: 1.6;
}
.number {
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
  font-weight: 600;
}
.positive {
  color: var(--success);
}
.negative {
  color: var(--danger);
}
.task-link {
  max-width: 170px;
  font-family: monospace;
  font-size: 12px;
}
.empty {
  padding: 32px 0;
  text-align: center;
  color: var(--muted);
}
.pager {
  margin-top: 24px;
}
@media (max-width: 600px) {
  .card {
    padding: 18px;
  }
  .filters label {
    min-width: 0;
    flex: 1;
  }
  table {
    min-width: 700px;
  }
  th,
  td {
    padding: 12px 8px;
  }
}
</style>
