<script setup lang="ts">
import { onMounted, ref } from 'vue'
import ApiDocs from './ApiDocs.vue'
import { labels, usePortal } from '../stores/portal'
const store = usePortal()
const section = ref('docs')
const authMode = ref('login')
const password = ref('')
const emailName = ref('')
async function showDocs() {
  section.value = 'docs'
  await store.loadModels()
}
async function submit() {
  const account = emailName.value.toLowerCase() + '@star-net.cn'
  await store.auth(authMode.value, account, password.value)
  password.value = ''
  if (store.user) section.value = 'account'
  else if (store.message) {
    authMode.value = 'login'
  }
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
        <p class="eyebrow">COMPANY MODEL API</p>
        <h1>开发者中心</h1>
      </div>
      <nav>
        <button :class="{ secondary: section !== 'docs' }" @click="showDocs">API 文档</button
        ><button
          v-if="store.user"
          :class="{ secondary: section !== 'account' }"
          @click="section = 'account'"
        >
          我的用量与积分</button
        ><button v-if="!store.user" class="secondary" @click="section = 'auth'">登录 / 注册</button
        ><button v-else class="secondary" @click="store.logout">退出登录</button>
      </nav>
    </header>
    <p v-if="store.error" class="error" role="alert">{{ store.error }}</p>
    <p v-if="store.message" role="status">{{ store.message }}</p>
    <ApiDocs v-if="section === 'docs'" />
    <section v-else-if="!store.user" class="card auth">
      <h2>{{ authMode === 'register' ? '注册账号' : '登录开发者中心' }}</h2>
      <p class="muted">
        仅支持 @star-net.cn 公司邮箱注册。注册后由管理员生成、绑定密钥并分配积分。
      </p>
      <form @submit.prevent="submit">
        <label>
          公司邮箱
          <span class="email-account">
            <input
              v-model="emailName"
              aria-label="公司邮箱前缀"
              required
              maxlength="68"
              autocomplete="username"
              pattern="[A-Za-z0-9_\-]+(\.[A-Za-z0-9_\-]+)*"
              placeholder="zhangjiaqi"
            />
            <span>@star-net.cn</span>
          </span>
        </label>
        <label
          >密码<input
            v-model="password"
            required
            type="password"
            minlength="10"
            maxlength="128"
            :autocomplete="authMode === 'register' ? 'new-password' : 'current-password'" /></label
        ><button :disabled="store.loading">{{ authMode === 'register' ? '注册' : '登录' }}</button
        ><button
          type="button"
          class="secondary"
          @click="authMode = authMode === 'register' ? 'login' : 'register'"
        >
          {{ authMode === 'register' ? '已有账号，登录' : '创建账号' }}
        </button>
      </form>
    </section>
    <template v-else
      ><section class="card">
        <div class="heading">
          <h2>{{ store.user.username }} 的账户</h2>
          <button :disabled="store.loading" class="secondary" @click="store.reload">刷新</button>
        </div>
        <p class="muted">用户 ID：{{ store.user.id }} · 1 积分 = ¥0.01</p>
        <p v-if="!store.user.keys.length">尚未分配 API Key，请等待管理员生成与绑定。</p>
        <div class="accounts">
          <article v-for="key in store.user.keys" :key="key.id" class="card">
            <h3>
              {{ key.name }} <small>{{ key.enabled ? '已启用' : '已停用' }}</small>
            </h3>
            <code>{{ key.key_prefix }}…</code>
            <p>
              可用积分 <strong>{{ key.available_points }}</strong>
            </p>
            <p>本月额度 {{ key.monthly_points }} · 剩余 {{ key.monthly_balance }}</p>
            <p>临时余额 {{ key.extra_balance }} · 预占 {{ key.reserved_points }}</p>
            <p class="muted">额度周期 {{ key.billing_month }}，北京时间每月重置。</p>
          </article>
        </div>
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
                {{ job.billing.points ?? '待核账' }}
                <p v-if="job.billing.cny !== null">¥{{ job.billing.cny }}</p>
                <p>预占 {{ job.billing.reserved_points }}</p>
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
              <td>{{ Number(row.points) > 0 ? '+' : '' }}{{ row.points }}</td>
              <td>{{ row.monthly_after }} / {{ row.extra_after }}</td>
              <td>
                {{ row.reason }}
                <p v-if="row.job_id">
                  <code>{{ row.job_id }}</code>
                </p>
                <details>
                  <summary>核算明细</summary>
                  <pre>{{ JSON.stringify(row.evidence, null, 2) }}</pre>
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
.auth {
  max-width: 500px;
  margin: 50px auto;
}
form {
  display: grid;
  gap: 18px;
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
