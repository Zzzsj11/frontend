<script setup lang="ts">
import FinancialInput from './FinancialInput.vue'
import { ref } from 'vue'
import { api } from '../api/client'
const props = defineProps<{
  route: { id: string; model_id: string; supplier: string; pricing: Record<string, any> }
}>()
const emit = defineEmits<{ saved: []; close: [] }>()
const fields: [string, string, number][] = [
  ['ascii_chars_per_token', '英文字符 / Token', 4],
  ['non_ascii_tokens_per_char', '中文等字符的 Token 系数', 1.5],
  ['message_overhead_tokens', '消息附加 Token', 12],
  ['default_output_tokens', '默认文本输出 Token', 512],
  ['image_low_tokens', '低质量图片默认 Token', 512],
  ['image_medium_tokens', '中质量图片默认 Token', 2048],
  ['image_high_tokens', '高质量 / auto 图片默认 Token', 8192],
  ['image_2k_multiplier', '2K 图片 Token 倍率', 2],
  ['image_4k_multiplier', '4K 图片 Token 倍率', 4],
  ['reference_image_tokens', '每张参考图输入 Token', 1536],
  ['cost_multiplier', '费用调整倍率', 1],
  ['fixed_cny', '每次固定加价（元）', 0],
  ['minimum_cny', '最低预估费用（元）', 0],
  ['range_low', '参考区间下侧系数', 0.5],
  ['range_high', '参考区间上侧系数', 1.5],
]
const policy = ref<Record<string, any>>(
  Object.fromEntries(
    fields.map(([key, , value]) => [key, props.route.pricing.estimate_policy?.[key] ?? value]),
  ),
)
policy.value.use_history = props.route.pricing.estimate_policy?.use_history ?? true
const rules = ref(JSON.stringify(props.route.pricing.estimate_rules || [], null, 2))
const error = ref('')
const saving = ref(false)
async function save() {
  saving.value = true
  error.value = ''
  try {
    await api('/routes/' + props.route.id + '/estimate-pricing', 'PUT', {
      policy: policy.value,
      rules: JSON.parse(rules.value),
    })
    emit('saved')
  } catch (e) {
    error.value = String(e)
  } finally {
    saving.value = false
  }
}
</script>
<template>
  <section class="card">
    <h3>预估费用配置 · {{ route.model_id }} / {{ route.supplier }}</h3>
    <p>
      预估人民币 = max（最低费用，Σ（预计用量 ÷ 计价单位 × 人民币单价）× 费用倍率 +
      固定加价）。平台积分 = 人民币 × 100。
    </p>
    <p class="muted">
      保存后仅影响本模型、本渠道的新报价；供应商同步不会覆盖手工配置。实际扣费与历史任务不变。
    </p>
    <form @submit.prevent="save">
      <div class="fields">
        <label v-for="[key, label] in fields" :key="key"
          >{{ label
          }}<FinancialInput
            v-if="key.endsWith('_cny')"
            v-model="policy[key]"
            kind="money"
            required
            :aria-label="label" />
          <input
            v-else
            v-model.number="policy[key]"
            type="number"
            step="any"
            required
            :aria-label="label"
        /></label>
      </div>
      <label
        ><input v-model="policy.use_history" type="checkbox" />
        优先使用同模型、同渠道历史用量</label
      >
      <details open>
        <summary>计价公式与规格条件</summary>
        <p>
          按顺序匹配
          conditions：resolution（如720p）、quality、has_video_input、duration、input_max。rates 中
          path 是用量，unit 是计价单位，cny 是人民币单价。例如每百万输出 Token 10
          元：path=output_tokens、unit=1000000、cny=10。
        </p>
        <textarea
          v-model="rules"
          rows="18"
          aria-label="预估计价规则 JSON"
          spellcheck="false"
        ></textarea>
      </details>
      <p v-if="error" role="alert">{{ error }}</p>
      <button :disabled="saving">保存预估配置</button>
      <button type="button" class="secondary" @click="emit('close')">关闭</button>
    </form>
  </section>
</template>
<style scoped>
textarea {
  width: 100%;
  font-family: monospace;
}
.fields {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
  gap: 14px;
}
</style>
