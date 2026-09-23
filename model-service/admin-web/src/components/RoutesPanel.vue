<script setup lang="ts">
import { financialDetails } from '../utils/financial'
import { onMounted, ref } from 'vue'
import { api } from '../api/client'
import EstimatePricingEditor from './EstimatePricingEditor.vue'
import RouteVerification from './RouteVerification.vue'
interface Route {
  id: string
  model_id: string
  supplier: string
  provider_model: string
  enabled: boolean
  priority: number
  concurrency: number
  verification: string
  capabilities: Record<string, unknown>
  pricing: Record<string, unknown>
}
const rows = ref<Route[]>([])
const error = ref('')
const message = ref('')
const editing = ref<Route | null>(null)
const verifying = ref<Route | null>(null)
async function savedVerification() {
  verifying.value = null
  message.value = '验收已登记，可单独启用路由；正式扣费仍需已发布费率'
  await load()
}
async function savedEstimate() {
  editing.value = null
  message.value = '预估配置已保存，已记录修改历史'
  await load()
}
async function load() {
  try {
    rows.value = await api<Route[]>('/routes')
  } catch (e) {
    error.value = String(e)
  }
}
async function save(row: Route) {
  error.value = ''
  message.value = ''
  try {
    await api('/routes/' + row.id, 'PATCH', {
      enabled: row.enabled,
      priority: row.priority,
      concurrency: row.concurrency,
    })
    message.value = '配置已保存，仅影响新任务'
    await load()
  } catch (e) {
    error.value = String(e)
    await load()
  }
}
onMounted(load)
</script>
<template>
  <section class="card table-wrap">
    <h3>模型供应商路由</h3>
    <p class="muted">
      每个模型、每个渠道可独立修改并发上限（1–200）。实际并发还受模型总上限、调用方与渠道总上限约束。数字越小优先级越高。
    </p>
    <p v-if="error" role="alert" class="error">{{ error }}</p>
    <p v-if="message" role="status">{{ message }}</p>
    <table>
      <thead>
        <tr>
          <th>统一模型 / 供应商</th>
          <th>上游模型</th>
          <th>验证</th>
          <th>优先级</th>
          <th>渠道并发上限</th>
          <th>启用</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="row.id">
          <td>
            {{ row.model_id }}<br />{{
              row.supplier === 'yseeai'
                ? '英和海外'
                : row.supplier === 'yinghe'
                  ? '英和国内'
                  : row.supplier === 'toapis'
                    ? 'Toapis'
                    : row.supplier
            }}
          </td>
          <td>
            {{ row.provider_model }}
            <details>
              <summary>能力与费率快照</summary>
              <pre>{{
                JSON.stringify(
                  financialDetails({ capabilities: row.capabilities, pricing: row.pricing }),
                  null,
                  2,
                )
              }}</pre>
            </details>
          </td>
          <td>{{ row.verification }}</td>
          <td>
            <input
              v-model.number="row.priority"
              type="number"
              min="0"
              max="1000"
              :aria-label="row.id + '优先级'"
            />
          </td>
          <td>
            <input
              v-model.number="row.concurrency"
              type="number"
              min="1"
              max="200"
              :aria-label="row.id + '并发'"
            />
          </td>
          <td>
            <input
              v-model="row.enabled"
              type="checkbox"
              :disabled="row.verification !== 'passed'"
              :aria-label="row.id + '启用'"
            />
          </td>
          <td>
            <button @click="save(row)">保存</button
            ><button class="secondary" @click="editing = row">配置预估费用</button>
            <button class="secondary" @click="verifying = row">登记验收</button>
          </td>
        </tr>
      </tbody>
    </table>
  </section>
  <EstimatePricingEditor
    v-if="editing"
    :key="editing.id"
    :route="editing"
    @saved="savedEstimate"
    @close="editing = null"
  />
  <RouteVerification
    v-if="verifying"
    :key="verifying.id"
    :route="verifying"
    @saved="savedVerification"
    @close="verifying = null"
  />
</template>
