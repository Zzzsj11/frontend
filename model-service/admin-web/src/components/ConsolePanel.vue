<script setup lang="ts">
import { ref } from 'vue'
import RoutesPanel from './RoutesPanel.vue'
import WalletPanel from './WalletPanel.vue'
import ChannelBalancesPanel from './ChannelBalancesPanel.vue'
import PricingPanel from './PricingPanel.vue'
import JobsPanel from './JobsPanel.vue'
import AdminLogin from './AdminLogin.vue'
import AdminPassword from './AdminPassword.vue'
import { useControl } from '../stores/control'
const store = useControl()
const sections = [
  { id: 'jobs', label: '任务与用量' },
  { id: 'models', label: '模型管理' },
  { id: 'routes', label: '模型供应商' },
  { id: 'clients', label: '调用方密钥' },
  { id: 'wallets', label: '用户与积分' },
  { id: 'balances', label: '渠道余额' },
  { id: 'pricing', label: '生成方式费率' },
  { id: 'audits', label: '操作审计' },
  { id: 'password', label: '修改密码' },
]
const section = ref('jobs')
const clientName = ref('')
const requireAgent = ref(false)
async function createClient() {
  await store.createClient(clientName.value, requireAgent.value)
  clientName.value = ''
}
function changeLimit(id: string, event: Event) {
  const m = store.models.find((m) => m.id === id)
  if (m)
    void store.changeModel(m, { concurrency: Number((event.target as HTMLInputElement).value) })
}
</script>
<template>
  <AdminLogin v-if="!store.authenticated" />
  <div v-else class="shell">
    <aside>
      <p class="eyebrow">MODEL SERVICE</p>
      <h1>模型控制台</h1>
      <nav>
        <button
          v-for="item in sections"
          :key="item.id"
          :class="{ active: section === item.id }"
          @click="section = item.id"
        >
          {{ item.label }}
        </button>
      </nav>
      <p class="muted">管理服务可独立发布<br />生成任务持续运行</p>
      <button class="secondary" @click="store.logout">退出登录</button>
    </aside>
    <main>
      <header>
        <div>
          <p class="eyebrow">CONTROL PLANE</p>
          <h2>{{ sections.find((item) => item.id === section)?.label }}</h2>
        </div>
        <button class="secondary" :disabled="store.loading" @click="store.reload">
          {{ store.loading ? '加载中…' : '刷新' }}
        </button>
      </header>
      <p v-if="store.error && section !== 'password'" role="alert" class="error">
        {{ store.error }}
      </p>
      <section class="stats">
        <article v-for="item in store.counts" :key="item.status + item.origin" class="card">
          <span>{{ item.status }} · {{ item.origin === 'agent_test' ? 'Agent 测试' : '业务' }}</span
          ><strong>{{ item.count }}</strong>
        </article>
        <article v-if="!store.counts.length" class="card">暂无调用记录</article>
      </section>
      <AdminPassword v-if="section === 'password'" />
      <RoutesPanel v-if="section === 'routes'" />
      <ChannelBalancesPanel v-if="section === 'balances'" />
      <WalletPanel v-if="section === 'wallets'" />
      <PricingPanel v-if="section === 'pricing'" />
      <JobsPanel v-if="section === 'jobs'" />
      <section v-if="section === 'models'" class="card table-wrap">
        <table>
          <thead>
            <tr>
              <th>模型</th>
              <th>渠道 / 类型</th>
              <th>并发上限</th>
              <th>状态</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="model in store.models" :key="model.id">
              <td>
                {{ model.id }}
                <details>
                  <summary>能力配置</summary>
                  <pre>{{ JSON.stringify(model.capabilities, null, 2) }}</pre>
                </details>
              </td>
              <td>{{ model.channel }} / {{ model.kind }}</td>
              <td>
                <input
                  :aria-label="model.id + ' 并发上限'"
                  type="number"
                  min="1"
                  max="200"
                  :value="model.concurrency"
                  @change="changeLimit(model.id, $event)"
                />
              </td>
              <td>
                <button
                  :disabled="store.loading"
                  :class="{ secondary: !model.enabled }"
                  @click="store.changeModel(model, { enabled: !model.enabled })"
                >
                  {{ model.enabled ? '已启用' : '已停用' }}
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </section>
      <section v-if="section === 'clients'" class="card">
        <form class="filters" @submit.prevent="createClient">
          <label
            >调用方名称<input v-model="clientName" required placeholder="例如：MV 系统" /></label
          ><label class="check"
            ><input v-model="requireAgent" type="checkbox" />仅允许 Agent 测试</label
          ><button :disabled="store.loading">创建 API Key</button>
        </form>
        <div v-if="store.revealedKey" class="key">
          <p>新密钥仅展示一次，请保存至调用方的 Secret。</p>
          <code>{{ store.revealedKey }}</code
          ><button class="secondary" @click="store.revealedKey = ''">已保存，隐藏</button>
        </div>
        <table>
          <thead>
            <tr>
              <th>调用方</th>
              <th>密钥前缀</th>
              <th>类型</th>
              <th>状态</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="client in store.clients" :key="client.id">
              <td>{{ client.name }}</td>
              <td>{{ client.key_prefix }}…</td>
              <td>{{ client.require_agent ? 'Agent 测试' : '业务系统' }}</td>
              <td>
                <button :disabled="store.loading" @click="store.toggleClient(client)">
                  {{ client.enabled ? '已启用' : '已停用' }}
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </section>
      <section v-if="section === 'audits'" class="card table-wrap">
        <table>
          <thead>
            <tr>
              <th>时间</th>
              <th>操作者</th>
              <th>操作</th>
              <th>目标</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in store.audits" :key="row.id">
              <td>{{ row.created_at }}</td>
              <td>{{ row.actor }}</td>
              <td>{{ row.action }}</td>
              <td>{{ row.target }}</td>
            </tr>
          </tbody>
        </table>
      </section>
    </main>
  </div>
</template>
<style scoped>
.login {
  max-width: 440px;
  margin: 12vh auto;
}
.login form {
  display: grid;
  gap: 18px;
}
.shell {
  display: grid;
  grid-template-columns: 240px 1fr;
  min-height: 100vh;
}
aside {
  padding: 32px 24px;
  background: var(--panel);
  border-right: 1px solid var(--border);
}
nav {
  display: grid;
  gap: 8px;
  margin: 40px 0;
}
nav button {
  background: transparent;
  color: var(--text);
  text-align: left;
}
nav button.active {
  background: var(--primary-light);
  color: var(--primary);
}
main {
  padding: 32px;
  min-width: 0;
}
header,
footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 24px;
}
footer {
  margin-top: 24px;
}
.stats {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
  margin-bottom: 24px;
}
.stats .card {
  min-width: 140px;
}
.stats strong {
  display: block;
  font-size: 28px;
  margin-top: 12px;
}
.filters {
  display: flex;
  align-items: end;
  gap: 16px;
  flex-wrap: wrap;
}
.check {
  display: flex;
  align-items: center;
}
.check input {
  width: auto;
}
.key {
  background: var(--primary-light);
  padding: 20px;
  margin-top: 20px;
  overflow-wrap: anywhere;
}
.key button {
  margin-left: 12px;
}
@media (max-width: 800px) {
  .shell {
    grid-template-columns: 1fr;
  }
  aside {
    padding: 16px;
  }
  nav {
    display: flex;
    flex-wrap: wrap;
    margin: 16px 0;
  }
  main {
    padding: 16px;
  }
}
</style>
