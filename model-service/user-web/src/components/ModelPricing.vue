<script setup lang="ts">
import { labels, type Model } from '../stores/portal'
import { money, moneyPoints } from '../utils/financial'
defineProps<{ model: Model }>()
</script>
<template>
  <section class="pricing">
    <h3>积分费率</h3>
    <article v-for="(rule, index) in model.pricing" :key="rule.id || index">
      <h4>
        {{ labels[rule.selector?.mode || ''] || '全部生成方式' }} ·
        {{ rule.selector?.resolution || '全部规格' }} · {{ rule.confirmed ? '已发布' : '待配置' }}
      </h4>
      <p v-if="rule.selector?.quality || rule.selector?.sound" class="muted">
        质量：{{ rule.selector?.quality || '全部' }} · 声音：{{ rule.selector?.sound || '全部' }}
      </p>
      <div v-if="rule.rates.length" class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>用量</th>
              <th>人民币费率</th>
              <th>积分费率</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="rate in rule.rates" :key="rate.path">
              <td>
                {{ rate.label
                }}<small
                  >{{ rate.path
                  }}<span v-if="rate.subtract?.length"
                    >（减去 {{ rate.subtract.join('、') }}）</span
                  ></small
                >
              </td>
              <td>¥{{ money(rate.cny) }} / {{ rate.unit }}</td>
              <td>{{ moneyPoints(rate.cny) }} 积分 / {{ rate.unit }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <p v-else class="muted">尚未配置可展示费率，请联系管理员。</p>
    </article>
    <p class="muted">
      按实际用量和任务接收时的费率结算。失败任务如产生实际费用仍会计费；用量缺失时待核账。
    </p>
  </section>
</template>
<style scoped>
.pricing {
  border-top: 1px solid var(--border);
  margin-top: 24px;
  padding-top: 8px;
}
small {
  display: block;
  color: var(--muted);
  margin-top: 6px;
}
</style>
