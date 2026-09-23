<script setup lang="ts">
import { ref } from 'vue'
import { api } from '../api/client'
const props = defineProps<{ route: { id: string; model_id: string; supplier: string } }>()
const emit = defineEmits<{ saved: []; close: [] }>()
const jobId = ref('')
const note = ref('')
const parameters = ref(false)
const result = ref(false)
const usage = ref(false)
const error = ref('')
const saving = ref(false)
async function save() {
  saving.value = true
  error.value = ''
  try {
    await api('/routes/' + props.route.id + '/verify', 'POST', {
      job_id: jobId.value,
      review_note: note.value,
      parameters_checked: parameters.value,
      result_checked: result.value,
      usage_checked: usage.value,
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
    <h3>登记路由验收 · {{ route.model_id }} / {{ route.supplier }}</h3>
    <p>
      使用已有成功测试工单，核对请求规格、实际产物与用量后登记。登记不会发起生成；启用路由和发布正式费率需分别操作。
    </p>
    <p v-if="error" role="alert" class="error">{{ error }}</p>
    <form @submit.prevent="save">
      <label>验收工单 ID<input v-model="jobId" required maxlength="160" /></label>
      <label>验收记录<textarea v-model="note" required minlength="10" maxlength="2000" /></label>
      <label
        ><input
          v-model="parameters"
          type="checkbox"
          required
        />已核对请求尺寸、画质、时长等规格</label
      >
      <label><input v-model="result" type="checkbox" required />已检查实际产物与请求是否一致</label>
      <label><input v-model="usage" type="checkbox" required />已核对归因和实际用量记录</label>
      <button :disabled="saving">{{ saving ? '保存中…' : '登记验收通过' }}</button>
      <button type="button" class="secondary" @click="emit('close')">取消验收登记</button>
    </form>
  </section>
</template>
