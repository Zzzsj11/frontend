<script setup lang="ts">
import { points, signedPoints, financialDetails } from '../utils/financial'
import { onMounted, ref } from 'vue'
import { api } from '../api/client'
import { useControl } from '../stores/control'
import AccountManagement from './AccountManagement.vue'
import FinancialInput from './FinancialInput.vue'
interface User {
  id: string
  username: string
  enabled: boolean
}
interface Wallet {
  billing_enabled: boolean
  id: string
  name: string
  user_id: string | null
  monthly_points: string
  monthly_balance: string
  extra_balance: string
  available_points: string
  reserved_points: string
  key_prefix: string
}
interface Ledger {
  id: string
  kind: string
  points: string
  reason: string
  actor: string
  created_at: string
  job_id: string | null
  client_id: string
  evidence: unknown
}
const store = useControl()
const users = ref<User[]>([]),
  wallets = ref<Wallet[]>([]),
  ledger = ref<Ledger[]>([])
const keyId = ref(''),
  quota = ref('0'),
  delta = ref(''),
  reason = ref(''),
  filter = ref(''),
  kind = ref(''),
  page = ref(1),
  total = ref(0)
const operation = ref(crypto.randomUUID())
const labels: Record<string, string> = {
  monthly_reset: '月度重置',
  manual_credit: '临时增加',
  manual_debit: '临时扣减',
  task_charge: '任务消费',
  reconciliation: '账单校正',
}
async function load() {
  const [u, w, l] = await Promise.all([
    api<User[]>('/users'),
    api<Wallet[]>('/wallets'),
    api<{ items: Ledger[]; total: number }>(
      `/ledger?client_id=${filter.value}&kind=${kind.value}&page=${page.value}`,
    ),
  ])
  users.value = u
  wallets.value = w
  ledger.value = l.items
  total.value = l.total
}
async function refresh() {
  await store.execute(load)
}
function choose() {
  quota.value = wallets.value.find((w) => w.id === keyId.value)?.monthly_points || '0'
  operation.value = crypto.randomUUID()
}
async function saveQuota() {
  await store.execute(async () => {
    await api(`/clients/${keyId.value}/quota`, 'POST', { points: quota.value })
    await load()
  })
}
async function adjust() {
  await store.execute(async () => {
    await api(`/clients/${keyId.value}/adjust`, 'POST', {
      points: delta.value,
      reason: reason.value,
      operation_id: operation.value,
    })
    delta.value = ''
    reason.value = ''
    operation.value = crypto.randomUUID()
    await load()
  })
}
function changeOperation() {
  operation.value = crypto.randomUUID()
}
async function changePage(n: number) {
  page.value += n
  await refresh()
}
onMounted(refresh)
</script>
<template>
  <AccountManagement />
  <section class="card table-wrap">
    <h3>Key 额度与余额</h3>
    <table>
      <thead>
        <tr>
          <th>Key / 用户</th>
          <th>每月额度</th>
          <th>本月余额</th>
          <th>临时余额</th>
          <th>预占 / 可用</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="w in wallets" :key="w.id">
          <td>
            {{ w.name }} · {{ w.key_prefix }}…
            <p>{{ users.find((u) => u.id === w.user_id)?.username || '未绑定（系统 Key）' }}</p>
          </td>
          <td>{{ w.billing_enabled ? points(w.monthly_points) : '旧系统 Key：额度控制未启用' }}</td>
          <td>{{ points(w.monthly_balance) }}</td>
          <td>{{ points(w.extra_balance) }}</td>
          <td>{{ points(w.reserved_points) }} / {{ points(w.available_points) }}</td>
        </tr>
      </tbody>
    </table>
    <p class="muted">用户 Key 的月上限由账号持有者自行分配。以下操作仅用于系统 Key。</p>
    <label
      >选择系统 Key<select aria-label="选择系统 Key" v-model="keyId" @change="choose">
        <option value="">请选择</option>
        <option v-for="w in wallets.filter((w) => !w.user_id)" :key="w.id" :value="w.id">
          {{ w.name }} · {{ w.key_prefix }}
        </option>
      </select></label
    ><template v-if="keyId"
      ><form class="fields" @submit.prevent="saveQuota">
        <label
          >新的每月重置额度<FinancialInput
            v-model="quota"
            type="number"
            min="0"
            step="0.000001"
            required /></label
        ><button :disabled="store.loading">保存下月额度</button>
      </form>
      <p class="muted">
        北京时间每月 1
        日重置；修改额度从下月生效，不抹去本月消费。要立即增加或减少可用积分，请使用下方临时调整。
      </p>
      <form class="fields" @submit.prevent="adjust">
        <label
          >调整积分（正数增加、负数扣减）<FinancialInput
            v-model="delta"
            type="number"
            step="0.000001"
            required
            @input="changeOperation" /></label
        ><label
          >原因<input v-model="reason" minlength="3" required @input="changeOperation" /></label
        ><button :disabled="store.loading">记录并执行调整</button>
      </form></template
    >
  </section>
  <section class="card table-wrap">
    <h3>不可覆盖的积分流水</h3>
    <div class="fields">
      <label
        >Key 筛选<select aria-label="Key 筛选" v-model="filter" @change="refresh">
          <option value="">全部</option>
          <option v-for="w in wallets" :key="w.id" :value="w.id">{{ w.name }}</option>
        </select></label
      ><label
        >类型<select aria-label="类型" v-model="kind" @change="refresh">
          <option value="">全部</option>
          <option v-for="(label, id) in labels" :key="id" :value="id">{{ label }}</option>
        </select></label
      ><button class="secondary" :disabled="store.loading" @click="refresh">刷新账本</button>
    </div>
    <table>
      <thead>
        <tr>
          <th>时间 / Key</th>
          <th>类型</th>
          <th>积分变动</th>
          <th>操作者</th>
          <th>原因</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="r in ledger" :key="r.id">
          <td>
            {{ r.created_at }}
            <p>{{ wallets.find((w) => w.id === r.client_id)?.name }}</p>
          </td>
          <td>
            <strong :class="{ error: Number(r.points) < 0 }">{{ labels[r.kind] || r.kind }}</strong>
          </td>
          <td>{{ signedPoints(r.points) }}</td>
          <td>{{ r.actor }}</td>
          <td>
            {{ r.reason }}
            <p>{{ r.job_id }}</p>
            <details>
              <summary>凭据与明细</summary>
              <pre>{{ JSON.stringify(financialDetails(r.evidence), null, 2) }}</pre>
            </details>
          </td>
        </tr>
      </tbody>
    </table>
    <footer>
      <button class="secondary" :disabled="page === 1 || store.loading" @click="changePage(-1)">
        上一页</button
      ><span>{{ page }} 页 / {{ total }} 条</span
      ><button
        class="secondary"
        :disabled="page * 50 >= total || store.loading"
        @click="changePage(1)"
      >
        下一页
      </button>
    </footer>
  </section>
</template>
<style scoped>
input[type='number'] {
  width: 100%;
}
.card {
  margin-bottom: 20px;
}
.fields {
  display: flex;
  align-items: end;
  flex-wrap: wrap;
  gap: 16px;
  margin: 20px 0;
}
label {
  flex: 1;
  min-width: 200px;
}
.key {
  padding: 20px;
  background: var(--primary-light);
  margin-top: 20px;
  overflow-wrap: anywhere;
}
footer {
  display: flex;
  align-items: center;
  gap: 16px;
}
</style>
