<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
const props = defineProps<{ phase?: string; submittedAt?: string; hasAssets: boolean }>()
const labels: Record<string, string> = {
  queued: '等待提交',
  platform_queued: '平台排队中',
  provider_running: '视频生成中',
  reviewing_assets: '人物素材审核中',
  archiving: '素材保存中',
  reconciling: '状态核对中',
  manual_review: '待人工核对，请联系开发人员，不能重新生成',
}
const now = ref(Date.now())
let timer: ReturnType<typeof setInterval> | undefined
onMounted(() => {
  timer = setInterval(() => {
    now.value = Date.now()
  }, 1000)
})
onUnmounted(() => clearInterval(timer))
const elapsed = computed(() => {
  const start = Date.parse(props.submittedAt || '')
  if (!Number.isFinite(start)) return ''
  const seconds = Math.max(0, Math.floor((now.value - start) / 1000))
  return `，已等待 ${Math.floor(seconds / 60)}分${String(seconds % 60).padStart(2, '0')}秒`
})
</script>
<template>
  <span class="hint" role="status"
    >{{ labels[phase || ''] || '视频处理中' }}{{ elapsed
    }}{{ hasAssets ? '（已有素材可预览）' : '' }}</span
  >
</template>
