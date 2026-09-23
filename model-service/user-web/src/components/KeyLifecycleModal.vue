<script setup lang="ts">
import { computed } from 'vue'
import BaseModal from './base/BaseModal.vue'
import { usePortal, type Key } from '../stores/portal'
const props = defineProps<{ target: Key | null }>()
const emit = defineEmits<{ close: [] }>()
const store = usePortal()
const action = computed(() => (props.target?.enabled ? '撤销' : '删除'))
async function confirm() {
  if (!props.target) return
  if (props.target.enabled) await store.revokeKey(props.target.id)
  else await store.deleteKey(props.target.id)
  if (!store.error) emit('close')
}
</script>
<template>
  <BaseModal
    :open="!!target"
    :title="action + ' API Key'"
    :loading="store.loading"
    @close="emit('close')"
  >
    <p v-if="target?.enabled">
      确认撤销「{{ target.name }}」？撤销后该 Key 将立即失效，无法恢复使用。
    </p>
    <p v-else>确认删除已撤销的「{{ target?.name }}」？删除后将不再显示在 Key 列表中。</p>
    <p class="muted">历史消费和在途任务保留，仍计入账号额度。</p>
    <p v-if="store.error" role="alert" class="error">{{ store.error }}</p>
    <template #footer>
      <button class="secondary" :disabled="store.loading" @click="emit('close')">取消</button>
      <button class="danger" :disabled="store.loading" @click="confirm">
        {{ store.loading ? '处理中…' : '确认' + action }}
      </button>
    </template>
  </BaseModal>
</template>
<style scoped>
.danger {
  background: var(--danger);
}
p {
  line-height: 1.7;
}
</style>
