<script setup lang="ts">
import { ref, watch } from 'vue'
import { usePortal } from '../stores/portal'
const store = usePortal()
const name = ref('')
const quota = ref('0')
const values = ref<Record<string, string>>({})
const deleting = ref('')
watch(
  () => store.user?.keys,
  (keys) => {
    values.value = Object.fromEntries((keys || []).map((key) => [key.id, key.monthly_points]))
  },
  { immediate: true },
)
async function create() {
  await store.createKey(name.value, quota.value)
  if (!store.error) name.value = ''
}
async function remove(id: string) {
  await store.deleteKey(id)
  deleting.value = ''
}
</script>
<template>
  <div v-if="store.user?.quota" class="quota-summary">
    <h3>账号月度总额度</h3>
    <p>
      月上限 <strong>{{ store.user.quota.monthly_points }}</strong> 积分 · 本月已用
      {{ store.user.quota.spent_points }} · 预占 {{ store.user.quota.reserved_points }} · 可用
      {{ store.user.quota.available_points }}
    </p>
    <p class="muted">
      {{ store.user.quota.billing_month }} · 北京时间每月 1 日更新。账号总额度由管理员设置。
    </p>
    <p>
      Key：{{ store.user.quota.key_count }} / {{ store.user.quota.key_limit }} · 已分配上限合计
      {{ store.user.quota.allocated_points }} 积分
    </p>
    <p class="muted">各 Key 上限之和可超过账号总额度；实际消费同时受 Key 和账号总额度限制。</p>
  </div>
  <p v-if="store.error" class="error" role="alert">{{ store.error }}</p>
  <p v-else-if="store.message" role="status">{{ store.message }}</p>
  <h3>我的 API Key</h3>
  <form class="fields" @submit.prevent="create">
    <label>Key 名称<input v-model="name" required maxlength="160" /></label>
    <label
      >Key 月消费上限<input
        v-model="quota"
        type="number"
        min="0"
        max="1000000000"
        step="0.000001"
        required
    /></label>
    <button
      :disabled="store.loading || (store.user?.keys.length || 0) >= 10 || !!store.revealedKey"
    >
      创建 Key
    </button>
  </form>
  <p v-if="store.user?.keys.length === 10" class="muted">已达到 10 个 Key 上限。</p>
  <div v-if="store.revealedKey" class="revealed" role="status">
    <p>Key 仅展示一次，请妥善保存，不要放入前端代码。</p>
    <code>{{ store.revealedKey }}</code>
    <button class="secondary" @click="store.revealedKey = ''">已保存，隐藏 Key</button>
  </div>
  <p v-if="!store.user?.keys.length">暂无 Key，请创建自己的 API Key。</p>
  <div class="keys">
    <article v-for="key in store.user?.keys" :key="key.id" class="card">
      <h3>
        {{ key.name }} <small>{{ key.enabled ? '已启用' : '已停用' }}</small>
      </h3>
      <code>{{ key.key_prefix }}…</code>
      <p>
        本月已用 {{ key.spent_points }} · 预占 {{ key.reserved_points }} · 当前可用
        {{ key.available_points }}
      </p>
      <form @submit.prevent="store.setKeyQuota(key.id, values[key.id])">
        <label
          >月消费上限<input
            v-model="values[key.id]"
            :aria-label="`${key.name} 月消费上限`"
            type="number"
            min="0"
            max="1000000000"
            step="0.000001"
            required
        /></label>
        <button :disabled="store.loading">保存月上限</button>
      </form>
      <p class="muted">立即生效，不清除本月已消费积分。</p>
      <button
        v-if="deleting !== key.id"
        class="secondary"
        :disabled="store.loading"
        @click="deleting = key.id"
      >
        删除 Key
      </button>
      <div v-else>
        <p>删除后该 Key 无法再调用模型，历史消费和在途任务仍计入账号额度。</p>
        <button :disabled="store.loading" @click="remove(key.id)">确认删除</button>
        <button class="secondary" @click="deleting = ''">取消</button>
      </div>
    </article>
  </div>
</template>
<style scoped>
input[type='number'] {
  width: 100%;
  min-width: 160px;
  max-width: 260px;
}
.fields {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
  align-items: end;
}
.fields label {
  flex: 1;
  min-width: 180px;
}
.keys {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(270px, 1fr));
  gap: 16px;
  margin-top: 20px;
}
form {
  display: grid;
  gap: 12px;
}
.revealed {
  padding: 20px;
  margin-top: 16px;
  background: var(--primary-light);
  overflow-wrap: anywhere;
}
.revealed button {
  display: block;
  margin-top: 12px;
}
</style>
