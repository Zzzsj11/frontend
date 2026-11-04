<script setup lang="ts">
import { ref } from 'vue'
import { apiRequest } from '../api/client'
const props = defineProps<{ jobId: string }>()
const emit = defineEmits<{ released: [] }>()
const open = ref(false)
const reason = ref('')
const confirmed = ref(false)
const busy = ref(false)
const error = ref('')
const release = async () => {
  busy.value = true
  try {
    await apiRequest(`/admin/jobs/${props.jobId}/release-review`, {
      method: 'POST',
      body: JSON.stringify({ reason: reason.value, confirmed_not_accepted: confirmed.value }),
    })
    emit('released')
    open.value = false
  } catch (e) {
    error.value = e instanceof Error ? e.message : '解除失败'
  } finally {
    busy.value = false
  }
}
</script>
<template>
  <button class="action" @click="open = !open">处理待人工核对</button>
  <div v-if="open">
    <p>仅平台确认未受理时解除。已受理的任务请同步原工单；解除不会自动生成或退款。</p>
    <label>核查依据<textarea v-model="reason" maxlength="2000" /></label>
    <label><input v-model="confirmed" type="checkbox" />已核实平台未受理，不存在执行中的任务</label>
    <button :disabled="busy || !confirmed || reason.trim().length < 5" @click="release">
      解除重试限制
    </button>
    <p role="alert">{{ error }}</p>
  </div>
</template>
