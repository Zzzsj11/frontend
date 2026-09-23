<script setup lang="ts">
import { labels, type Job } from '../stores/portal'
import { prettyPoints, money, localDate, financialDetails } from '../utils/financial'
import BaseModal from './base/BaseModal.vue'
defineProps<{ open: boolean; job: Job | null; loading: boolean; error: string }>()
const emit = defineEmits<{ close: [] }>()
const states: Record<string, string> = {
  queued: '排队中',
  running: '处理中',
  succeeded: '已完成',
  failed: '失败',
}
</script>
<template>
  <BaseModal :open="open" title="任务消费详情" @close="emit('close')">
    <p v-if="loading" role="status">正在加载任务详情…</p>
    <p v-else-if="error" role="alert" class="error">{{ error }}</p>
    <template v-else-if="job">
      <div class="detail-grid">
        <div>
          <span>模型</span><strong>{{ job.model }}</strong>
        </div>
        <div>
          <span>状态</span><strong>{{ states[job.status] || job.status }}</strong>
        </div>
        <div>
          <span>消费积分</span
          ><strong>{{
            job.billing.points == null ? '待核账' : prettyPoints(job.billing.points)
          }}</strong>
        </div>
        <div>
          <span>预占积分</span><strong>{{ prettyPoints(job.billing.reserved_points) }}</strong>
        </div>
      </div>
      <p>所属 Key：{{ job.key_name }}</p>
      <p>时间：{{ localDate(job.created_at) }}（北京时间）</p>
      <p>
        任务：<code>{{ job.id }}</code>
      </p>
      <p>
        {{ labels[job.billing.status] || job.billing.status
        }}<span v-if="job.billing.cny != null"> · ¥{{ money(job.billing.cny) }}</span>
      </p>
      <p v-if="job.error" class="error">{{ job.error }}</p>
      <details>
        <summary>实际用量与计价依据</summary>
        <pre>{{
          JSON.stringify(financialDetails({ usage: job.usage, pricing: job.billing.rule }), null, 2)
        }}</pre>
      </details>
    </template>
  </BaseModal>
</template>
<style scoped>
.detail-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}
.detail-grid div {
  padding: 16px;
  background: var(--bg);
  border-radius: var(--radius-sm);
}
.detail-grid span {
  color: var(--muted);
  font-size: 13px;
}
.detail-grid strong {
  display: block;
  margin-top: 8px;
}
p {
  font-size: 14px;
  line-height: 1.6;
}
</style>
