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
  <section class="card routes-panel">
    <h3>模型供应商路由</h3>
    <p class="muted">
      每个模型、每个渠道可独立修改并发上限（1–1000）。实际并发还受模型总上限、调用方与渠道总上限约束。数字越小优先级越高。
    </p>
    <p v-if="error" role="alert" class="error">{{ error }}</p>
    <p v-if="message" role="status">{{ message }}</p>
    <div class="table-wrap">
      <table>
        <colgroup>
          <col class="model-column" />
          <col class="provider-column" />
          <col class="verification-column" />
          <col class="number-column" />
          <col class="concurrency-column" />
          <col class="enabled-column" />
          <col class="actions-column" />
        </colgroup>
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
            <td>
              <span class="verification-status">{{
                row.verification === 'passed' ? '已验收' : '待验收'
              }}</span>
            </td>
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
                max="1000"
                :aria-label="row.id + '并发'"
              />
            </td>
            <td>
              <div class="switch-field">
                <button
                  type="button"
                  role="switch"
                  class="route-switch"
                  :class="{ active: row.enabled }"
                  :aria-checked="row.enabled"
                  :disabled="row.verification !== 'passed'"
                  :aria-label="row.id + '启用'"
                  :title="
                    row.verification !== 'passed'
                      ? '请先登记验收，再启用路由'
                      : '切换后点击保存生效'
                  "
                  @click="row.enabled = !row.enabled"
                >
                  <span class="switch-thumb" />
                </button>
                <span class="switch-label">{{ row.enabled ? '已启用' : '已停用' }}</span>
              </div>
            </td>
            <td>
              <div class="route-actions">
                <button @click="save(row)">保存</button
                ><button class="secondary" @click="editing = row">配置预估费用</button>
                <button class="secondary" @click="verifying = row">登记验收</button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
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

<style scoped>
.routes-panel {
  min-width: 0;
}
table {
  table-layout: fixed;
  min-width: 1120px;
}
.model-column {
  width: 20%;
}
.provider-column {
  width: 24%;
}
.verification-column {
  width: 88px;
}
.number-column {
  width: 100px;
}
.concurrency-column {
  width: 124px;
}
.enabled-column {
  width: 100px;
}
.actions-column {
  width: 210px;
}
th {
  white-space: nowrap;
}
td {
  overflow-wrap: anywhere;
  vertical-align: middle;
}
td input[type='number'] {
  width: 100%;
  margin: 0;
}
.route-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.route-actions button {
  margin: 0;
  padding: 8px 10px;
  white-space: nowrap;
}
.verification-status,
.switch-label {
  color: var(--muted);
  font-size: 12px;
  white-space: nowrap;
}
.switch-field {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 6px;
}
.route-switch {
  display: inline-flex;
  align-items: center;
  width: 44px;
  height: 26px;
  padding: 3px;
  margin: 0;
  border-radius: var(--radius-lg);
  background: var(--muted);
  flex-shrink: 0;
}
.route-switch.active {
  background: var(--primary);
}
.route-switch:focus-visible {
  outline: 2px solid var(--primary);
  outline-offset: 3px;
}
.switch-thumb {
  display: block;
  width: 18px;
  height: 18px;
  border-radius: var(--radius-lg);
  background: var(--panel);
  transition: transform 0.15s ease;
}
.route-switch.active .switch-thumb {
  transform: translateX(18px);
}
@media (prefers-reduced-motion: reduce) {
  .switch-thumb {
    transition: none;
  }
}
@media (max-width: 640px) {
  .routes-panel {
    padding: 16px;
  }
}
</style>
