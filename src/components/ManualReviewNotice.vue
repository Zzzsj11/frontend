<script setup lang="ts">
import { ref } from 'vue'
const props = defineProps<{ jobId?: string; lineNumber: number }>()
const copied = ref(false)
const copy = async () => {
  await navigator.clipboard.writeText(
    `视频待人工核对：镜头 ${props.lineNumber}，工单 ${props.jobId || '请从管理后台查询'}。提交结果无法确认，请开发人员核查后解除限制。`,
  )
  copied.value = true
}
</script>
<template>
  <div class="review-notice" role="status">
    <strong>待人工核对 · 不能重新生成</strong>
    <p>上次请求的提交结果无法确认。重复点击不会发起新任务，请联系开发人员核对并解除限制。</p>
    <button type="button" @click.stop="copy">{{ copied ? '已复制' : '复制排查信息' }}</button>
  </div>
</template>
<style scoped>
.review-notice {
  color: var(--warning);
  background: var(--warning-light);
  padding: 8px;
  border-radius: var(--radius-sm);
  font-size: var(--font-sm);
}
</style>
