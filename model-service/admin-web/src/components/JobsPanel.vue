<script setup lang="ts">
import { points, financialDetails } from '../utils/financial'
import { useControl } from '../stores/control'
const store = useControl()
async function page(delta: number) {
  store.page += delta
  await store.reload()
}
</script>
<template>
  <section class="card">
    <form class="filters" @submit.prevent="store.reload">
      <label
        >来源<select v-model="store.origin">
          <option value="">全部</option>
          <option value="business">正常业务</option>
          <option value="agent_test">Agent 开发测试</option>
        </select></label
      ><label
        >状态<select v-model="store.status">
          <option value="">全部</option>
          <option
            v-for="s in [
              'queued',
              'running',
              'succeeded',
              'failed',
              'recoverable',
              'manual_review',
            ]"
            :key="s"
          >
            {{ s }}
          </option>
        </select></label
      ><label>Agent 批次<input v-model="store.run" placeholder="完整批次 ID" /></label
      ><button>查询</button>
    </form>
    <p class="muted">
      展示渠道原始用量。金额未定价不代表免费；提交结果不确定的任务需要核对，不能直接重发。
    </p>
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>任务 / 模型</th>
            <th>状态</th>
            <th>来源 / 批次</th>
            <th>用量</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="job in store.jobs" :key="job.id">
            <td>
              {{ job.model }}<small>{{ job.id }}</small>
            </td>
            <td>
              <span class="badge">{{ job.status }}</span>
            </td>
            <td>
              {{ job.origin === 'agent_test' ? 'Agent 开发测试' : '正常业务'
              }}<small>{{ job.agent_name }} {{ job.agent_run_id }}</small>
            </td>
            <td>
              <p>
                {{ job.billing.points === null ? '待核账' : points(job.billing.points) }} 积分 ·
                {{ job.billing.status }}
              </p>
              <code>{{ JSON.stringify(financialDetails(job.usage)) }}</code>
            </td>
            <td>
              <button class="secondary" @click="store.inspect(job)">详情</button
              ><button
                v-if="job.status === 'recoverable'"
                :disabled="store.loading"
                @click="store.recover(job)"
              >
                恢复查询 / 归档
              </button>
            </td>
          </tr>
          <tr v-if="!store.jobs.length">
            <td colspan="5">暂无符合条件的任务</td>
          </tr>
        </tbody>
      </table>
    </div>
    <footer>
      <button class="secondary" :disabled="store.page <= 1" @click="page(-1)">上一页</button
      ><span>第 {{ store.page }} 页 · {{ store.total }} 条</span
      ><button class="secondary" :disabled="store.page * 50 >= store.total" @click="page(1)">
        下一页
      </button>
    </footer>
    <details v-if="store.detail" open>
      <summary>任务详情</summary>
      <pre>{{ JSON.stringify(financialDetails(store.detail), null, 2) }}</pre>
    </details>
  </section>
</template>
<style scoped>
.filters {
  display: flex;
  align-items: end;
  gap: 16px;
  flex-wrap: wrap;
}
footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 24px;
}
.badge {
  background: var(--primary-light);
  color: var(--primary);
  padding: 5px 10px;
  border-radius: var(--radius-sm);
}
small {
  display: block;
  font-size: 12px;
  color: var(--muted);
  max-width: 320px;
  overflow-wrap: anywhere;
}
</style>
