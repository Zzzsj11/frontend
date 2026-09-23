<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { alphabetical, modelVendor } from '../utils/modelCatalog'
import CodeExample from './CodeExample.vue'
import { labels, usePortal } from '../stores/portal'
const store = usePortal()
const search = ref('')
const selected = ref('')
const category = ref('')
const searchInput = ref<HTMLInputElement | null>(null)
function clearSearch() {
  search.value = ''
  searchInput.value?.focus()
}
const models = computed(() =>
  store.models.filter(
    (m) =>
      m.enabled &&
      (category.value === 'text' ? ['chat', 'text'].includes(m.kind) : m.kind === category.value) &&
      m.id.toLowerCase().includes(search.value.toLowerCase()),
  ),
)
const groups = computed(() => {
  const vendors = [...new Set(models.value.map((m) => modelVendor(m.id)))].sort(alphabetical)
  return vendors.map((vendor) => ({
    vendor,
    models: models.value
      .filter((m) => modelVendor(m.id) === vendor)
      .sort((a, b) => alphabetical(a.id, b.id)),
  }))
})
watch(category, () => {
  selected.value = ''
  search.value = ''
})
watch(models, (items) => {
  if (!items.some((m) => m.id === selected.value)) selected.value = ''
})
const model = computed(() => models.value.find((m) => m.id === selected.value))
const example = computed(() => {
  const m = model.value
  const name = (m?.id || '').replace(/^yseeai--/, '').replace(/^(svip-|s-|z-)/, '')
  const responses = m?.capabilities.native_endpoint === '/v1/responses'
  const body = responses
    ? { model: m?.id, input: '你好', max_output_tokens: 128 }
    : m?.kind === 'chat'
      ? { model: m.id, messages: [{ role: 'user', content: '你好' }], max_tokens: 128 }
      : m?.kind === 'image'
        ? { model: m.id, prompt: '清晨的海边', size: '1024x1024', quality: 'medium' }
        : {
            model: m?.id || 'MODEL_ID',
            prompt: '清晨的海边，镜头缓慢前移',
            duration: name.startsWith('veo-') ? 8 : name === 'gemini-omni-flash-preview' ? 10 : 5,
            resolution: '720p',
            reference_mode: 'text',
          }
  return `curl -X POST "$MODEL_API_BASE/v1/${responses ? 'responses' : m?.kind === 'chat' ? (name.startsWith('claude') ? 'messages' : 'chat/completions') : m?.kind === 'image' ? 'images' : 'videos'}" \\\n  -H "Authorization: Bearer $MODEL_API_KEY" \\\n  -H "Idempotency-Key: unique-request-id" \\\n  -H "Content-Type: application/json" \\\n  -d '${JSON.stringify(body, null, 2)}'`
})
</script>
<template>
  <section class="card">
    <p class="eyebrow">API REFERENCE</p>
    <h2>一次接入，多种模型</h2>
    <p>联系管理员开通账号及月额度 → 登录创建自己的 API Key → 发起任务 → 查询积分明细。</p>
    <p class="muted">
      每个账号最多创建 10 个 Key；Key 明文仅在创建时展示一次，请保存到服务端环境变量。
    </p>
    <details>
      <summary>鉴权、任务状态与错误码</summary>
      <p>API 地址和 Bearer Token 由管理员提供。</p>
      <p>
        每次生成必须携带唯一 Idempotency-Key；重复同一 key 返回原任务，改变参数返回 409。查询 GET
        /v1/jobs/{id}，状态依次 queued / running / succeeded/failed。
      </p>
      <p>
        401：鉴权失败；402：积分不足；403：无模型权限；422：参数错误；429：并发限制；503：模型费率尚未配置。失败任务如有实际用量仍可计费，用量缺失显示待核账。
      </p>
    </details>
  </section>
  <section class="card">
    <h3>只估价，不生成</h3>
    <p>
      在文本、图片或视频请求中增加 <code>estimate_only: true</code>，或调用
      <code>POST /v1/pricing/estimate</code>。估价不扣积分、不创建生成任务，无需 Idempotency-Key。
    </p>
    <p class="muted">
      文本和图片会根据输入内容、生成规格及历史用量自动给出参考价，无需填写 Token。 可用
      estimate_usage 覆盖预计用量。参考区间不代表价格保证，最终费用以实际生成用量为准。
    </p>
    <CodeExample
      :code="
        JSON.stringify(
          {
            model: 'gpt-5.6-sol',
            estimate_only: true,
            messages: [{ role: 'user', content: '帮我写一段产品介绍' }],
            max_tokens: 500,
          },
          null,
          2,
        )
      "
    />
  </section>
  <section class="card">
    <h3>模型与积分费率</h3>
    <div class="model-search">
      <label for="model-search-input">搜索模型</label>
      <div class="search-field">
        <input
          id="model-search-input"
          ref="searchInput"
          v-model="search"
          placeholder="输入模型名称"
        />
        <button
          v-if="search"
          type="button"
          class="clear-search"
          aria-label="清除搜索"
          title="清除搜索"
          @click="clearSearch"
        >
          <svg
            viewBox="0 0 20 20"
            fill="none"
            stroke="currentColor"
            stroke-width="1.8"
            aria-hidden="true"
          >
            <path d="m6 6 8 8M14 6l-8 8" />
          </svg>
        </button>
      </div>
    </div>
    <div class="model-selectors">
      <label
        >模型类型<select v-model="category" aria-label="模型类型">
          <option value="">请选择模型类型</option>
          <option value="text">文本</option>
          <option value="image">图片</option>
          <option value="video">视频</option>
        </select></label
      >
      <label
        >选择模型<select v-model="selected" aria-label="选择模型" :disabled="!category">
          <option value="">
            {{ !category ? '请先选择模型类型' : models.length ? '请选择模型' : '没有匹配的模型' }}
          </option>
          <optgroup v-for="group in groups" :key="group.vendor" :label="group.vendor">
            <option v-for="m in group.models" :key="m.id" :value="m.id">
              {{ m.id }}
            </option>
          </optgroup>
        </select></label
      >
    </div>
    <template v-if="model"
      ><h3>{{ model.id }}</h3>
      <details>
        <summary>模型参数限制</summary>
        <pre>{{ JSON.stringify(model.capabilities, null, 2) }}</pre>
      </details>
      <article v-for="(rule, index) in model.pricing" :key="rule.id || index" class="rule">
        <h4>
          {{ labels[rule.selector?.mode || ''] || '全部生成方式' }} ·
          {{ rule.selector?.resolution || '全部规格' }} · {{ rule.confirmed ? '已发布' : '待配置' }}
        </h4>
        <p v-if="rule.selector?.quality || rule.selector?.sound">
          质量：{{ rule.selector?.quality || '全部' }}；声音：{{ rule.selector?.sound || '全部' }}
        </p>
        <div class="table-wrap">
          <table v-if="rule.rates.length">
            <thead>
              <tr>
                <th>用量</th>
                <th>返回字段</th>
                <th>人民币费率</th>
                <th>积分费率</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="r in rule.rates" :key="r.path">
                <td>{{ r.label }}</td>
                <td>
                  {{ r.path
                  }}<small v-if="r.subtract?.length"> 减去 {{ r.subtract.join('、') }}</small>
                </td>
                <td>¥{{ r.cny }} / {{ r.unit }}</td>
                <td>{{ Number(r.cny) * 100 }} 积分 / {{ r.unit }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </article>
      <p v-if="model.id === 'minimax-h3-runninghub' || model.kind === 'text'" class="muted">
        此模型使用工作流/提示词优化原生接口，请向管理员获取对应工作流参数；下方统一生成示例不适用。
      </p>
      <h3 v-else>请求示例</h3>
      <p class="muted">
        以下为文生示例。视频须按上方能力限制调整 duration；参考素材通过 images 原图 URL
        数组传入，reference_mode 可选 reference、first_frame、first_last，具体支持以模型能力为准。
      </p>
      <CodeExample
        v-if="model.id !== 'minimax-h3-runninghub' && model.kind !== 'text'"
        :code="example"
      />
    </template>
    <p v-else class="muted">请选择模型，查看每种生成方式及规格的具体费率。</p>
  </section>
</template>
<style scoped>
.card {
  margin-bottom: 20px;
}
.rule {
  border-top: 1px solid var(--border);
  margin-top: 20px;
  padding-top: 8px;
}
.model-search {
  display: block;
  max-width: 360px;
  margin: 16px 0;
}
.search-field {
  position: relative;
}
.search-field input {
  padding-right: 42px;
}
.clear-search {
  position: absolute;
  right: 6px;
  top: 50%;
  transform: translateY(-50%);
  display: grid;
  place-items: center;
  width: 30px;
  height: 30px;
  padding: 0;
  background: transparent;
  color: var(--muted);
}
.clear-search:hover {
  background: var(--bg);
  color: var(--text);
}
.clear-search svg {
  width: 18px;
  height: 18px;
}
.model-selectors {
  display: grid;
  grid-template-columns: minmax(140px, 1fr) minmax(0, 2fr);
  gap: 20px;
  margin: 16px 0 24px;
}
.model-selectors label {
  min-width: 0;
}
@media (max-width: 600px) {
  .model-selectors {
    grid-template-columns: minmax(90px, 1fr) minmax(0, 2fr);
    gap: 12px;
  }
}
</style>
