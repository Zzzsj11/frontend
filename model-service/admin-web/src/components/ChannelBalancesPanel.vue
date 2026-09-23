<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import {
  listBalances,
  recordBalance,
  refreshBalance,
  savePolicy,
  type BalancePolicy,
  type ChannelBalance,
  type Currency,
} from '../api/channelBalances'
import { useControl } from '../stores/control'

const store = useControl()
const rows = ref<ChannelBalance[]>([])
const selectedId = ref('')
const selected = computed(() => rows.value.find((row) => row.id === selectedId.value))
const policy = ref<BalancePolicy>({
  currency: 'CNY',
  usd_cny: '6.9',
  points_per_unit: null,
  points_currency: 'CNY',
})
const manualAmount = ref('')
const manualNote = ref('')
const message = ref('')
const labels: Record<Currency, string> = {
  CNY: '人民币',
  USD: '美元',
  POINTS: '积分',
  UNKNOWN: '待确认',
}
let timer: ReturnType<typeof setInterval> | undefined
let fetching = false

function amount(value: string | null) {
  return value === null ? '—' : Number(value).toLocaleString('zh-CN', { maximumFractionDigits: 6 })
}
function time(value: string | null) {
  return value
    ? new Date(
        value.endsWith('Z') || /[+-]\d\d:\d\d$/.test(value) ? value : value + 'Z',
      ).toLocaleString('zh-CN')
    : '尚未查询'
}
function conversion(row: ChannelBalance) {
  if (row.channel === 'toapis') return '1000 Toapis 积分 = ¥35（每积分 ¥0.035）'
  if (row.currency === 'CNY') return '1 元 = ¥1'
  if (row.currency === 'USD') return `US$1 = ¥${amount(row.usd_cny)}`
  if (row.currency === 'POINTS' && row.points_per_unit)
    return `${amount(row.points_per_unit)} 积分 = ${row.points_currency === 'USD' ? 'US$1' : '¥1'}${row.points_currency === 'USD' ? `；US$1 = ¥${amount(row.usd_cny)}` : ''}`
  return '兑换比例待配置'
}
async function load() {
  if (fetching) return
  fetching = true
  try {
    rows.value = await listBalances()
  } finally {
    fetching = false
  }
}
function edit(row: ChannelBalance) {
  selectedId.value = row.id
  policy.value = {
    currency: row.currency,
    usd_cny: row.usd_cny,
    points_per_unit: row.points_per_unit,
    points_currency: row.points_currency,
  }
  manualAmount.value = ''
  manualNote.value = ''
  message.value = ''
}
async function save() {
  await store.execute(async () => {
    await savePolicy(selectedId.value, {
      ...policy.value,
      points_per_unit: policy.value.points_per_unit || null,
    })
    message.value = '兑换配置已保存，人民币参考值已更新。'
    await load()
  })
}
async function refresh(row: ChannelBalance) {
  await store.execute(async () => {
    await refreshBalance(row.id)
    message.value = `${row.name} 已安排查询；执行服务处理后自动更新，连续刷新间隔至少 60 秒。`
  })
}
async function record() {
  await store.execute(async () => {
    await recordBalance(selectedId.value, manualAmount.value, manualNote.value)
    message.value = '人工余额快照已保存并记录审计。'
    manualAmount.value = manualNote.value = ''
    await load()
  })
}
onMounted(() => {
  void store.execute(load)
  timer = setInterval(() => {
    if (document.visibilityState === 'visible')
      void load().catch(() => {
        store.error = '渠道余额列表刷新失败，请重试'
      })
  }, 10000)
})
onUnmounted(() => {
  if (timer) clearInterval(timer)
})
</script>

<template>
  <section class="card">
    <div class="heading">
      <div>
        <h3>渠道账户余额</h3>
        <p class="muted">
          原币种保留精度，人民币金额仅作参考折算。商户资金与 Key
          限额分别展示，不重复汇总共享商户余额。
        </p>
      </div>
      <button class="secondary" :disabled="store.loading" @click="store.execute(load)">
        刷新列表
      </button>
    </div>
    <p v-if="message" role="status">{{ message }}</p>
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>渠道 / Key</th>
            <th>商户余额（原币种）</th>
            <th>人民币参考值</th>
            <th>Key 限额</th>
            <th>来源 / 更新时间</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in rows" :key="row.id">
            <td>
              <strong>{{ row.name }}</strong>
              <p class="muted">{{ row.key_masked || '尚未取得 Key 信息' }}</p>
            </td>
            <td>
              {{ amount(row.balance) }} {{ labels[row.currency] }}
              <p v-if="row.error" class="error">{{ row.error }}</p>
              <p v-if="row.stale && row.balance !== null" class="error">历史快照，请刷新核对</p>
            </td>
            <td>
              {{ row.cny_balance === null ? '待查询 / 待配置' : '≈ ¥' + amount(row.cny_balance) }}
              <p class="muted">{{ conversion(row) }}</p>
            </td>
            <td>
              <template v-if="row.quota"
                ><p>{{ row.quota.name }}</p>
                <p>
                  {{
                    row.quota.unlimited
                      ? '未设 Key 限额'
                      : '限额剩余：' + amount(row.quota.remaining) + ' ' + labels[row.currency]
                  }}
                </p>
                <p class="muted">
                  已用：{{ amount(row.quota.used) }} {{ labels[row.currency] }}；不代表商户总消费
                </p></template
              >
              <span v-else>—</span>
              <p v-if="row.quota_error" class="error">{{ row.quota_error }}</p>
            </td>
            <td>
              {{
                row.source === 'provider'
                  ? '供应商查询'
                  : row.source === 'manual'
                    ? '人工录入'
                    : '暂无数据'
              }}
              <p class="muted">{{ time(row.queried_at) }}</p>
              <p v-if="!row.automatic" class="muted">查询接口待接入，可录入快照</p>
            </td>
            <td>
              <button v-if="row.automatic" :disabled="store.loading" @click="refresh(row)">
                刷新余额</button
              ><button class="secondary" @click="edit(row)">设置</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
  <section v-if="selected" class="card settings">
    <h3>{{ selected.name }} · 币种与兑换配置</h3>
    <p v-if="selected.channel === 'toapis'">
      1000 Toapis 积分 = ¥35；费用按实扣积分 × ¥0.035 计算。
    </p>
    <form v-else class="fields" @submit.prevent="save">
      <label
        >余额币种<select
          v-model="policy.currency"
          :disabled="selected.automatic"
          aria-label="余额币种"
        >
          <option v-for="(label, code) in labels" :key="code" :value="code">{{ label }}</option>
        </select></label
      >
      <label
        v-if="
          policy.currency === 'USD' ||
          (policy.currency === 'POINTS' && policy.points_currency === 'USD')
        "
        >1 美元对应人民币<input
          v-model="policy.usd_cny"
          inputmode="decimal"
          required
          aria-label="美元人民币汇率"
      /></label>
      <template v-if="policy.currency === 'POINTS'">
        <label
          >多少积分兑换 1 单位货币<input
            v-model="policy.points_per_unit"
            inputmode="decimal"
            placeholder="待配置"
            aria-label="积分兑换比例"
        /></label>
        <label
          >积分兑换币种<select v-model="policy.points_currency" aria-label="积分兑换币种">
            <option value="CNY">人民币（元）</option>
            <option value="USD">美元</option>
          </select></label
        >
      </template>
      <button :disabled="store.loading">保存兑换配置</button>
    </form>
    <p class="muted">
      兑换配置仅影响余额参考展示，不修改供应商余额、用户积分或历史任务账单。修改原币种会清空原余额快照，需重新录入。
    </p>
    <form v-if="!selected.automatic" class="fields" @submit.prevent="record">
      <label
        >原币种余额<input v-model="manualAmount" inputmode="decimal" required aria-label="人工余额"
      /></label>
      <label
        >核对来源与备注<input
          v-model="manualNote"
          required
          maxlength="500"
          placeholder="例如：供应商控制台，今日核对"
      /></label>
      <button :disabled="store.loading || selected.currency === 'UNKNOWN'">保存人工快照</button>
    </form>
  </section>
</template>

<style scoped>
.heading,
.fields {
  display: flex;
  gap: 20px;
  align-items: end;
  justify-content: space-between;
  flex-wrap: wrap;
}
.heading {
  align-items: center;
}
.settings {
  margin-top: 24px;
}
.fields {
  justify-content: start;
}
td {
  vertical-align: top;
  min-width: 150px;
}
td p {
  margin: 6px 0;
}
h3 {
  margin-top: 0;
}
</style>
