<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { apiRequest } from '../api/client'
import BaseSelect from './base/BaseSelect.vue'

interface Row {
  username: string
  jobId: string
  model: string
  origin: string
  agentName: string
  agentRunId: string
  points: string | null
}
const username = ref('')
const origin = ref('')
const rows = ref<Row[]>([])
const offset = ref(0)
const loading = ref(false)
const error = ref('')
const more = ref(false)
async function load(start = 0) {
  loading.value = true
  error.value = ''
  try {
    const query = new URLSearchParams({
      username: username.value.trim(),
      origin: origin.value,
      offset: String(start),
      limit: '21',
    })
    const result = await apiRequest<Row[]>('/admin/image-billing?' + query)
    rows.value = result.slice(0, 20)
    more.value = result.length > 20
    offset.value = start
  } catch (e) {
    error.value = e instanceof Error ? e.message : '图片结算加载失败'
  } finally {
    loading.value = false
  }
}
onMounted(() => load())
</script>
<template>
  <section aria-label="图片积分结算">
    <h3>图片积分结算</h3>
    <form @submit.prevent="load()">
      <label>用户名 <input v-model="username" placeholder="全部用户" /></label>
      <BaseSelect v-model="origin" aria-label="图片生成来源">
        <option value="">全部来源</option>
        <option value="business">正常业务</option>
        <option value="agent_test">Agent 开发测试</option>
      </BaseSelect>
      <button :disabled="loading">查询图片结算</button>
    </form>
    <p v-if="error" role="alert">{{ error }}</p>
    <div v-else class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>用户</th>
            <th>图片工单</th>
            <th>模型</th>
            <th>实扣积分</th>
            <th>来源</th>
            <th>Agent / 批次</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in rows" :key="row.jobId">
            <td>{{ row.username }}</td>
            <td>{{ row.jobId }}</td>
            <td>{{ row.model }}</td>
            <td>{{ row.points === null ? '待结算' : Number(row.points) }}</td>
            <td>{{ row.origin === 'agent_test' ? 'Agent 开发测试' : '正常业务' }}</td>
            <td>{{ row.agentName }} {{ row.agentRunId }}</td>
          </tr>
        </tbody>
      </table>
      <p v-if="!loading && !rows.length">没有符合条件的图片工单</p>
      <button v-if="offset" :disabled="loading" @click="load(offset - 20)">上一页</button>
      <button v-if="more" :disabled="loading" @click="load(offset + 20)">下一页</button>
    </div>
  </section>
</template>
