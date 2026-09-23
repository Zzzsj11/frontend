<script setup lang="ts">
import CodeExample from './CodeExample.vue'
import ModelSearch from './ModelSearch.vue'
import CopyButton from './CopyButton.vue'
import ModelPricing from './ModelPricing.vue'
import { useApiDocs } from '../composables/useApiDocs'
const {
  search,
  selected,
  category,
  exampleId,
  categories,
  models,
  groups,
  model,
  docs,
  example,
  parameters,
  fullGuide,
  modelVendor,
} = useApiDocs()
</script>
<template>
  <section class="card model-browser" aria-label="API 模型目录">
    <ModelSearch v-model:category="category" v-model:search="search" :categories="categories" />
    <div class="company-list">
      <section v-for="group in groups" :key="group.vendor" :aria-label="group.vendor + ' 模型'">
        <h3>
          {{ group.vendor }} <small>{{ group.models.length }}</small>
        </h3>
        <div class="model-chips">
          <button
            v-for="item in group.models"
            :key="item.id"
            :aria-pressed="selected === item.id"
            :class="{ selected: selected === item.id }"
            @click="selected = item.id"
          >
            {{ item.id }}<small v-if="!item.enabled">暂未开放</small>
          </button>
        </div>
      </section>
    </div>
    <p v-if="!models.length" class="empty">
      {{ search ? '没有匹配的模型或公司' : '该类型暂无模型'
      }}<button v-if="search" class="link-button" @click="search = ''">清除搜索</button>
    </p>
  </section>
  <section v-if="model && docs" class="card model-docs" aria-label="当前模型文档">
    <div class="heading">
      <div>
        <p class="eyebrow">{{ modelVendor(model.id) }}</p>
        <h2>{{ model.id }}</h2>
      </div>
      <CopyButton :text="fullGuide" label="复制当前模型文档" />
    </div>
    <p v-if="!model.enabled" class="muted">
      当前模型暂未开放，示例供接入准备；可用性以管理员实际启用配置为准。
    </p>
    <template v-if="!docs.custom">
      <div class="example-tabs" role="group" aria-label="调用示例">
        <button
          v-for="item in docs.examples"
          :key="item.id"
          :class="{ secondary: exampleId !== item.id }"
          :aria-pressed="exampleId === item.id"
          @click="exampleId = item.id"
        >
          {{ item.label }}
        </button>
      </div>
      <template v-if="example"
        ><p>
          <code>{{ example.path }}</code>
        </p>
        <p class="muted">{{ example.hint }}</p>
        <CodeExample :code="example.code" copy-label="复制命令"
      /></template>
      <details class="responses">
        <summary>成功 / 失败响应示例（结构示意）</summary>
        <div class="response-grid">
          <div>
            <h4>创建成功</h4>
            <pre>{{ docs.success }}</pre>
          </div>
          <div>
            <h4>参数错误 · HTTP 422</h4>
            <pre>{{ docs.failure }}</pre>
          </div>
        </div>
        <p class="muted">
          示意省略部分字段；估价返回费用预估，查询返回任务当前状态，具体字段以实际响应为准。
        </p>
      </details>
      <details>
        <summary>请求参数与限制</summary>
        <div class="table-wrap">
          <table>
            <tbody>
              <tr v-for="param in parameters" :key="param.name">
                <th>{{ param.name }}</th>
                <td>{{ param.value }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </details>
    </template>
    <p v-else class="muted">此模型采用原生工作流接口，请联系管理员获取专用参数文档。</p>
    <ModelPricing :model="model" />
    <details>
      <summary>鉴权、任务状态与错误码</summary>
      <p class="muted">
        绑定账号的 Key 自动确定用户身份。生成请求使用唯一 Idempotency-Key；同
        Key、同参数重试不会重复创建任务，修改参数返回 409。任务查询 GET /v1/jobs/{id}，状态为 queued
        / running / succeeded / failed。
      </p>
      <p class="muted">
        401 鉴权失败 · 402 积分不足 · 403 无权限 · 409 请求冲突 · 422 参数错误 · 429 并发限制 · 503
        费率或服务暂不可用。
      </p>
    </details>
  </section>
</template>
<style scoped>
.card {
  margin-bottom: 24px;
}
h2 {
  font-size: 23px;
  overflow-wrap: anywhere;
}
.company-list {
  display: grid;
  gap: 18px;
  margin-top: 24px;
}
.company-list h3 {
  font-size: 14px;
  margin: 0 0 10px;
  color: var(--muted);
}
.company-list h3 small {
  font-weight: 400;
  margin-left: 6px;
}
.model-chips {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}
.model-chips button {
  background: var(--panel);
  border-color: var(--border);
  color: var(--text);
  text-align: left;
  font-size: 13px;
  max-width: 100%;
  overflow-wrap: anywhere;
}
.model-chips button.selected {
  border-color: var(--primary);
  background: var(--primary-light);
  color: var(--primary);
}
.model-chips small {
  display: block;
  margin-top: 5px;
  color: var(--muted);
  font-size: 11px;
}
.example-tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 24px;
}
.responses {
  margin-top: 24px;
}
.response-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}
.response-grid > div {
  min-width: 0;
}
.response-grid pre {
  background: var(--bg);
  padding: 16px;
  border-radius: var(--radius-sm);
  font-size: 12px;
}
.empty {
  text-align: center;
  padding: 24px;
  color: var(--muted);
}
.empty button {
  display: block;
  margin: 16px auto 0;
}
@media (max-width: 600px) {
  .card {
    padding: 18px;
  }
  .response-grid {
    grid-template-columns: 1fr;
  }
}
</style>
