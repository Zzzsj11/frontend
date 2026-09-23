<script setup lang="ts">
import { points, signedPoints, money, financialDetails } from '../utils/financial'
import { onMounted, ref, watch } from 'vue'
import ApiDocs from './ApiDocs.vue'
import PortalAuth from './PortalAuth.vue'
import UserKeys from './UserKeys.vue'
import { labels, usePortal } from '../stores/portal'
const store = usePortal()
const section = ref('docs')
watch(
  () => store.user,
  (user) => {
    if (user) section.value = 'account'
  },
)
async function showDocs() {
  section.value = 'docs'
  await store.loadModels()
}
async function page(delta: number) {
  store.page += delta
  await store.reload()
}
async function ledgerPage(delta: number) {
  store.ledgerPage += delta
  await store.reload()
}
onMounted(() => store.loadModels())
</script>
<template>
  <div class="portal-shell">
    <header>
      <div>
        <p class="eyebrow">ALL IN ONE MODEL API</p>
        <h1>模型中控台</h1>
      </div>
      <nav>
        <button
          v-if="!store.user?.must_change_password"
          :class="{ secondary: section !== 'docs' }"
          @click="showDocs"
        >
          API 文档</button
        ><button
          v-if="store.user && !store.user.must_change_password"
          :class="{ secondary: section !== 'account' }"
          @click="section = 'account'"
        >
          我的用量与积分</button
        ><button v-if="!store.user" class="secondary" @click="section = 'auth'">企业邮箱登录</button
        ><button v-else class="secondary" @click="store.logout">退出登录</button>
      </nav>
    </header>
    <p
      v-if="store.error && section === 'docs' && !store.user?.must_change_password"
      class="error"
      role="alert"
    >
      {{ store.error }}
    </p>
    <p
      v-if="store.message && section === 'docs' && !store.user?.must_change_password"
      role="status"
    >
      {{ store.message }}
    </p>
    <PortalAuth v-if="store.user?.must_change_password || (section !== 'docs' && !store.user)" />
    <ApiDocs v-else-if="section === 'docs'" />
    <template v-else-if="store.user"
      ><section class="card">
        <div class="heading">
          <h2>{{ store.user.username }} 的账户</h2>
          <button :disabled="store.loading" class="secondary" @click="store.reload">刷新</button>
        </div>
        <p class="muted">用户 ID：{{ store.user.id }} · 1 积分 = ¥0.01</p>
        <UserKeys />
      </section>
      <section class="card table-wrap">
        <h3>每次任务的积分消耗</h3>
        <table>
          <thead>
            <tr>
              <th>任务 / 时间</th>
              <th>模型</th>
              <th>生成状态</th>
              <th>积分</th>
              <th>计费依据</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="job in store.jobs" :key="job.id">
              <td>
                <code>{{ job.id }}</code>
                <p>{{ job.created_at }}</p>
              </td>
              <td>{{ job.model }}</td>
              <td>
                {{ job.status }}
                <p class="error">{{ job.error }}</p>
              </td>
              <td>
                {{ job.billing.points == null ? '待核账' : points(job.billing.points) }}
                <p v-if="job.billing.cny !== null">¥{{ money(job.billing.cny) }}</p>
                <p>预占 {{ points(job.billing.reserved_points) }}</p>
              </td>
              <td>
                {{ labels[job.billing.status] || job.billing.status }}
                <details>
                  <summary>实际用量与费率快照</summary>
                  <pre>{{
                    JSON.stringify({ usage: job.usage, pricing: job.billing.rule }, null, 2)
                  }}</pre>
                </details>
              </td>
            </tr>
          </tbody>
        </table>
        <p v-if="!store.jobs.length">暂无任务</p>
        <footer>
          <button class="secondary" :disabled="store.page === 1 || store.loading" @click="page(-1)">
            上一页</button
          ><span>{{ store.page }} 页 / {{ store.total }} 条</span
          ><button
            class="secondary"
            :disabled="store.page * 30 >= store.total || store.loading"
            @click="page(1)"
          >
            下一页
          </button>
        </footer>
      </section>
      <section class="card table-wrap">
        <h3>积分流水</h3>
        <table>
          <thead>
            <tr>
              <th>时间</th>
              <th>类型</th>
              <th>变动积分</th>
              <th>月 / 临时余额</th>
              <th>说明</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in store.ledger" :key="row.id">
              <td>{{ row.created_at }}</td>
              <td>
                <span class="badge" :class="{ negative: Number(row.points) < 0 }">{{
                  labels[row.kind] || row.kind
                }}</span>
              </td>
              <td>{{ signedPoints(row.points) }}</td>
              <td>{{ points(row.monthly_after) }} / {{ points(row.extra_after) }}</td>
              <td>
                {{ row.reason }}
                <p v-if="row.job_id">
                  <code>{{ row.job_id }}</code>
                </p>
                <details>
                  <summary>核算明细</summary>
                  <pre>{{ JSON.stringify(financialDetails(row.evidence), null, 2) }}</pre>
                </details>
              </td>
            </tr>
          </tbody>
        </table>
        <p v-if="!store.ledger.length">暂无流水</p>
        <footer>
          <button
            class="secondary"
            :disabled="store.ledgerPage === 1 || store.loading"
            @click="ledgerPage(-1)"
          >
            上一页</button
          ><span>{{ store.ledgerPage }} 页 / {{ store.ledgerTotal }} 条</span
          ><button
            class="secondary"
            :disabled="store.ledgerPage * 50 >= store.ledgerTotal || store.loading"
            @click="ledgerPage(1)"
          >
            下一页
          </button>
        </footer>
      </section>
    </template>
  </div>
</template>
<style scoped>
.portal-shell {
  max-width: 1440px;
  margin: auto;
  padding: 32px;
}
header,
.heading,
nav,
footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}
header {
  margin-bottom: 32px;
}
.card {
  margin-bottom: 20px;
}
.accounts {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(270px, 1fr));
  gap: 16px;
}
strong {
  font-size: 24px;
}
footer {
  margin-top: 20px;
}
.badge {
  display: inline-block;
  padding: 5px 8px;
  border-radius: var(--radius-sm);
  background: var(--primary-light);
  color: var(--primary);
  white-space: nowrap;
}
.badge.negative {
  color: var(--danger);
}
@media (max-width: 600px) {
  .portal-shell {
    padding: 16px;
  }
}
</style>
