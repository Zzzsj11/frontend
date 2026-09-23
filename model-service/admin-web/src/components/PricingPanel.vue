<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../api/client'
import { useControl } from '../stores/control'
interface Rate {
  label: string
  path: string
  unit: string
  cny: string
  optional: boolean
  subtract: string[]
}
interface Rule {
  id?: string
  selector: Record<string, string>
  confirmed: boolean
  description: string
  source: string
  reserve_points: string
  actual_cny_path: string
  rates: Rate[]
}
const store = useControl()
const pricing = ref<{ model: string; rules: Rule[] }[]>([])
const selected = ref('')
const edit = ref<Rule>(blank())
function blank(): Rule {
  return {
    selector: { mode: '', resolution: '', quality: '', sound: '' },
    confirmed: false,
    description: '按渠道返回的实际用量乘以当前账户适用费率计算积分',
    source: '管理员配置',
    reserve_points: '100',
    actual_cny_path: '',
    rates: [],
  }
}
async function load() {
  pricing.value = await api('/pricing')
}
function choose() {
  edit.value = blank()
}
function useRule(rule: Rule) {
  edit.value = JSON.parse(JSON.stringify({ ...blank(), ...rule }))
}
function addRate() {
  edit.value.rates.push({
    label: '输出 Token',
    path: 'completion_tokens',
    unit: '1000000',
    cny: '0',
    optional: false,
    subtract: [],
  })
}
function removeRate(index: number) {
  edit.value.rates.splice(index, 1)
}
function setSubtract(r: Rate, e: Event) {
  r.subtract = (e.target as HTMLInputElement).value
    .split(',')
    .map((v) => v.trim())
    .filter(Boolean)
}
async function save() {
  await store.execute(async () => {
    await api('/pricing/' + encodeURIComponent(selected.value), 'POST', edit.value)
    await load()
  })
}
onMounted(() => store.execute(load))
</script>
<template>
  <section class="card">
    <h3>模型 / 生成方式费率</h3>
    <p>
      1 积分 =
      ¥0.01。每个模型可按生成方式、规格、质量和声音分别配置。更具体的规则优先；新版本只影响后续任务。
    </p>
    <p class="muted">
      金额 = Σ（实际用量 ÷ 单位 × 人民币费率），积分 = 金额 × 100。缺少必需用量不会当作
      0。可选字段仅适用于供应商明确“缺省即 0”的字段。
    </p>
    <label
      >模型<select aria-label="模型" v-model="selected" @change="choose">
        <option value="">请选择</option>
        <option v-for="m in store.models" :key="m.id">{{ m.id }}</option>
      </select></label
    >
    <template v-if="selected"
      ><article
        v-for="(r, i) in pricing.find((p) => p.model === selected)?.rules || []"
        :key="r.id || i"
        class="rule"
      >
        <strong
          >{{ r.selector?.mode || '全部方式' }} · {{ r.selector?.resolution || '全部规格' }} ·
          {{ r.confirmed ? '已发布' : '待配置' }}</strong
        >
        <p>{{ r.description }}</p>
        <table v-if="r.rates.length">
          <thead>
            <tr>
              <th>计量</th>
              <th>人民币费率 / 单位</th>
              <th>积分 / 单位</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="rate in r.rates" :key="rate.path">
              <td>{{ rate.label }}（{{ rate.path }}）</td>
              <td>¥{{ rate.cny }} / {{ rate.unit }}</td>
              <td>{{ Number(rate.cny) * 100 }} / {{ rate.unit }}</td>
            </tr>
          </tbody>
        </table>
        <p>预占 {{ r.reserve_points }} 积分 · {{ r.source }}</p>
        <button class="secondary" @click="useRule(r)">以此编辑新版本</button>
      </article>
      <form @submit.prevent="save">
        <h3>发布费率版本</h3>
        <div class="fields">
          <label
            >生成方式<select aria-label="生成方式" v-model="edit.selector.mode">
              <option value="">全部方式（兜底）</option>
              <option value="chat">文本对话</option>
              <option value="text_to_image">文生图</option>
              <option value="image_to_image">图生图</option>
              <option value="text_to_video">文生视频</option>
              <option value="image_to_video">图生视频</option>
              <option value="reference_to_video">参考图生视频</option>
              <option value="first_last_frame">首尾帧视频</option>
              <option value="edit">续编 / 编辑</option>
            </select></label
          ><label
            >规格<input
              v-model="edit.selector.resolution"
              placeholder="720p、768p、2k、1024x1024；空为全部" /></label
          ><label
            >质量<input
              v-model="edit.selector.quality"
              placeholder="high、medium 等；空为全部" /></label
          ><label
            >声音<input v-model="edit.selector.sound" placeholder="on/off 或 true/false；空为全部"
          /></label>
        </div>
        <label>规则说明<input v-model="edit.description" required minlength="5" /></label
        ><label>费率来源 / 合同版本<input v-model="edit.source" required minlength="3" /></label
        ><label
          >单任务预占积分<input
            v-model="edit.reserve_points"
            type="number"
            min="0"
            step="0.000001"
            required
        /></label>
        <p class="muted">
          预占防止并发重复花费；不是最终扣款。设置为此规格的合理上限；超出预占的真实用量仍入账并阻止后续透支调用。
        </p>
        <div v-for="(r, i) in edit.rates" :key="i" class="rule">
          <div class="fields">
            <label>用量名称<input v-model="r.label" required /></label
            ><label
              >usage 字段路径<input v-model="r.path" placeholder="prompt_tokens" required /></label
            ><label
              >单位数量<input
                v-model="r.unit"
                type="number"
                min="0.000001"
                step="any"
                required /></label
            ><label
              >人民币单价<input
                v-model="r.cny"
                type="number"
                min="0"
                step="0.0000000001"
                required /></label
            ><label
              >需扣除的 usage 字段<input
                :value="r.subtract.join(',')"
                placeholder="prompt_tokens_details.cached_tokens"
                @input="setSubtract(r, $event)" /></label
            ><label>允许字段缺省为 0<input v-model="r.optional" type="checkbox" /></label>
          </div>
          <button type="button" class="secondary" @click="removeRate(i)">删除此计价项</button>
        </div>
        <button type="button" class="secondary" @click="addRate">增加计价项</button>
        <p class="muted">
          示例：输入 prompt_tokens，输出 completion_tokens；Anthropic 为 input_tokens /
          output_tokens。按秒计费只有渠道 usage 确实返回 output_seconds 才使用该字段。
        </p>
        <details>
          <summary>逐请求实付金额字段（可选）</summary>
          <label
            >人民币字段路径<input
              v-model="edit.actual_cny_path"
              placeholder="response.data.billing.actual_cny"
          /></label>
          <p>
            仅在已确认字段单位为人民币时配置，存在时优先按实付计费；不能直接把不明币种的 cost
            当人民币。
          </p>
        </details>
        <label class="check"
          ><input v-model="edit.confirmed" type="checkbox" />确认适用费率并启用此规则</label
        ><button :disabled="store.loading">发布新版本</button>
      </form></template
    >
  </section>
</template>
<style scoped>
input[type='number'] {
  width: 100%;
}
.fields {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 16px;
}
.rule {
  border-top: 1px solid var(--border);
  padding: 16px 0;
  margin-top: 16px;
}
form {
  display: grid;
  gap: 16px;
  margin-top: 24px;
}
.check {
  display: flex;
  align-items: center;
  gap: 8px;
}
input[type='checkbox'] {
  width: auto;
}
</style>
