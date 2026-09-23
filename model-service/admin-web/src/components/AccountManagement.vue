<script setup lang="ts">
import { points } from '../utils/financial'
import FinancialInput from './FinancialInput.vue'
import { onMounted, ref } from 'vue'
import { api } from '../api/client'
import { useControl } from '../stores/control'
interface Account {
  id: string
  username: string
  quota: {
    monthly_points: string
    spent_points: string
    reserved_points: string
    available_points: string
    key_count: number
    allocated_points: string
  }
}
const store = useControl()
const users = ref<Account[]>([])
const email = ref('')
const initialQuota = ref('0')
const revealed = ref<{ username: string; initial_password: string } | null>(null)
const values = ref<Record<string, string>>({})
async function load() {
  users.value = await api<Account[]>('/users')
  values.value = Object.fromEntries(users.value.map((u) => [u.id, u.quota.monthly_points]))
}
async function create() {
  await store.execute(async () => {
    revealed.value = await api('/users', 'POST', {
      username: email.value.toLowerCase() + '@star-net.cn',
      monthly_points: initialQuota.value,
    })
    email.value = ''
    await load()
  })
}
async function save(id: string) {
  await store.execute(async () => {
    await api(`/users/${id}/quota`, 'POST', { points: values.value[id] })
    await load()
  })
}
onMounted(() => store.execute(load))
</script>
<template>
  <section class="card">
    <h3>账号与月度总额度</h3>
    <p>管理员开通账号并设置月总额度；用户自行创建最多 10 个 Key、分配各 Key 月上限。</p>
    <form class="fields" @submit.prevent="create">
      <label
        >企业邮箱前缀<input
          v-model="email"
          aria-label="企业邮箱前缀"
          required
          maxlength="68"
          pattern="[A-Za-z0-9_\-]+(\.[A-Za-z0-9_\-]+)*"
          placeholder="star-net"
        /><span>@star-net.cn</span></label
      >
      <label
        >账号月总额度<FinancialInput
          v-model="initialQuota"
          type="number"
          min="0"
          max="1000000000"
          step="0.000001"
          required
      /></label>
      <button :disabled="store.loading || !!revealed">创建账号</button>
    </form>
    <div v-if="revealed" class="revealed">
      <p>账号已创建。初始密码仅展示一次，请通过安全渠道交付；首次登录必须修改密码。</p>
      <p>{{ revealed.username }}</p>
      <code aria-label="初始密码">{{ revealed.initial_password }}</code>
      <button class="secondary" @click="revealed = null">已保存，隐藏密码</button>
    </div>
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>账号</th>
            <th>Key 数量 / 分配上限合计</th>
            <th>本月已用 / 预占 / 可用</th>
            <th>账号月总额度</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="u in users" :key="u.id">
            <td>{{ u.username }}</td>
            <td>{{ u.quota.key_count }} / 10 · {{ points(u.quota.allocated_points) }}</td>
            <td>
              {{ points(u.quota.spent_points) }} / {{ points(u.quota.reserved_points) }} /
              {{ points(u.quota.available_points) }}
            </td>
            <td>
              <form @submit.prevent="save(u.id)">
                <FinancialInput
                  v-model="values[u.id]"
                  :aria-label="`${u.username} 账号月总额度`"
                  type="number"
                  min="0"
                  max="1000000000"
                  step="0.000001"
                  required
                /><button :disabled="store.loading">保存总额度</button>
              </form>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <p class="muted">
      北京时间自然月更新；修改立即生效，保留本月已用与预占。降低至已用额度以下时，将停止受理新任务。
    </p>
  </section>
</template>
<style scoped>
input[type='number'] {
  width: 100%;
  min-width: 160px;
  max-width: 260px;
}
.card {
  margin-bottom: 20px;
}
.fields {
  display: flex;
  align-items: end;
  gap: 16px;
  flex-wrap: wrap;
  margin: 20px 0;
}
.fields label {
  flex: 1;
  min-width: 200px;
}
.revealed {
  padding: 20px;
  background: var(--primary-light);
  overflow-wrap: anywhere;
}
.revealed button {
  display: block;
  margin-top: 12px;
}
</style>
