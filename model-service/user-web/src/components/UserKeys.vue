<script setup lang="ts">
import { ref } from 'vue'
import KeyReveal from './KeyReveal.vue'
import FinancialInput from './FinancialInput.vue'
import BaseModal from './base/BaseModal.vue'
import { usePortal, type Key } from '../stores/portal'
import { prettyPoints } from '../utils/financial'
const store = usePortal()
const creating = ref(false)
const editing = ref<Key | null>(null)
const deleting = ref<Key | null>(null)
const name = ref('')
const quota = ref('0')
function openCreate() {
  name.value = ''
  quota.value = '0'
  store.error = ''
  creating.value = true
}
function openEdit(key: Key) {
  quota.value = key.monthly_points
  editing.value = key
  store.error = ''
}
async function create() {
  await store.createKey(name.value, quota.value)
  if (store.revealedKey) creating.value = false
}
async function save() {
  if (!editing.value) return
  await store.setKeyQuota(editing.value.id, quota.value)
  if (!store.error) editing.value = null
}
async function remove() {
  if (!deleting.value) return
  await store.deleteKey(deleting.value.id)
  if (!store.error) deleting.value = null
}
</script>
<template>
  <section class="card keys-panel" aria-label="我的 API Key">
    <div class="heading">
      <div>
        <h2>
          我的 API Key <span class="pill">{{ store.user?.keys.length || 0 }} / 10</span>
        </h2>
        <p class="muted">各 Key 独立设置月上限，共享账号总额度。</p>
      </div>
      <button
        :disabled="store.loading || (store.user?.keys.length || 0) >= 10 || !!store.revealedKey"
        @click="openCreate"
      >
        创建 Key
      </button>
    </div>
    <p v-if="store.user?.quota" class="quota-note">
      账号月额度 <strong>{{ prettyPoints(store.user.quota.monthly_points) }}</strong> · 已分配 Key
      上限合计 <strong>{{ prettyPoints(store.user.quota.allocated_points) }}</strong> · 各 Key
      上限之和可超过账号总额度
    </p>
    <KeyReveal
      v-if="store.revealedKey"
      :api-key="store.revealedKey"
      @dismiss="store.revealedKey = ''"
    />
    <div class="key-list">
      <article
        v-for="key in store.user?.keys"
        :key="key.id"
        class="key-row"
        :aria-label="key.name + ' Key'"
      >
        <div class="key-identity">
          <strong>{{ key.name }}</strong
          ><code>{{ key.key_prefix }}…</code
          ><span class="pill">{{ key.enabled ? '已启用' : '已停用' }}</span>
        </div>
        <dl>
          <div>
            <dt>月消费上限</dt>
            <dd>{{ prettyPoints(key.monthly_points) }}</dd>
          </div>
          <div>
            <dt>本月已用</dt>
            <dd>{{ prettyPoints(key.spent_points) }}</dd>
          </div>
          <div>
            <dt>预占</dt>
            <dd>{{ prettyPoints(key.reserved_points) }}</dd>
          </div>
          <div>
            <dt>当前可用</dt>
            <dd>{{ prettyPoints(key.available_points) }}</dd>
          </div>
        </dl>
        <div class="key-actions">
          <button
            class="secondary"
            :aria-label="'修改 ' + key.name + ' 月上限'"
            :disabled="store.loading"
            @click="openEdit(key)"
          >
            修改月上限</button
          ><button
            class="link-button danger"
            :aria-label="'删除 ' + key.name"
            :disabled="store.loading"
            @click="deleting = key"
          >
            删除
          </button>
        </div>
      </article>
    </div>
    <div v-if="!store.user?.keys.length" class="empty">
      <h3>创建第一个 API Key</h3>
      <p>为不同应用分别创建 Key，便于分配额度和追踪消费。</p>
    </div>
    <p v-if="store.user?.keys.length === 10" class="muted">已达到 10 个 Key 上限。</p>
  </section>
  <BaseModal
    :open="creating"
    title="创建 API Key"
    :loading="store.loading"
    @close="creating = false"
  >
    <form class="key-form" @submit.prevent="create">
      <label
        >Key 名称<input
          v-model="name"
          required
          maxlength="160"
          placeholder="例如：内容生产应用" /></label
      ><label
        >Key 月消费上限<FinancialInput v-model="quota" min="0" max="1000000000" step="1" required
      /></label>
      <p class="muted">按北京时间自然月更新，实际使用同时受账号总额度限制。</p>
      <p v-if="store.error" role="alert" class="error">{{ store.error }}</p>
      <button :disabled="store.loading">{{ store.loading ? '创建中…' : '确认创建' }}</button>
    </form>
  </BaseModal>
  <BaseModal
    :open="!!editing"
    title="修改 Key 月上限"
    :loading="store.loading"
    @close="editing = null"
  >
    <form class="key-form" @submit.prevent="save">
      <p>{{ editing?.name }}</p>
      <label
        >月消费上限<FinancialInput
          v-model="quota"
          :aria-label="editing?.name + ' 月消费上限'"
          min="0"
          max="1000000000"
          step="1"
          required
      /></label>
      <p class="muted">立即生效，不清除本月已消费积分。</p>
      <p v-if="store.error" role="alert" class="error">{{ store.error }}</p>
      <button :disabled="store.loading">保存月上限</button>
    </form>
  </BaseModal>
  <BaseModal
    :open="!!deleting"
    title="删除 API Key"
    :loading="store.loading"
    @close="deleting = null"
    ><p>
      确认删除「{{ deleting?.name }}」？该 Key 将无法再调用模型，历史消费和在途任务仍计入账号额度。
    </p>
    <p v-if="store.error" role="alert" class="error">{{ store.error }}</p>
    <template #footer
      ><button class="secondary" :disabled="store.loading" @click="deleting = null">取消</button
      ><button class="delete-confirm" :disabled="store.loading" @click="remove">
        确认删除
      </button></template
    ></BaseModal
  >
</template>
<style scoped>
h2 {
  font-size: 22px;
}
h2 .pill {
  vertical-align: middle;
  margin-left: 8px;
}
.quota-note {
  color: var(--muted);
  font-size: 13px;
  background: var(--bg);
  border-radius: var(--radius-sm);
  padding: 14px 16px;
  line-height: 1.8;
}
.key-list {
  display: grid;
  gap: 12px;
  margin-top: 20px;
}
.key-row {
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 20px;
  display: grid;
  grid-template-columns: minmax(140px, 1fr) 2fr auto;
  align-items: center;
  gap: 24px;
}
.key-identity {
  display: grid;
  justify-items: start;
  gap: 8px;
  overflow-wrap: anywhere;
  min-width: 0;
}
.key-identity code {
  color: var(--muted);
}
dl {
  margin: 0;
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
}
dt {
  color: var(--muted);
  font-size: 12px;
}
dd {
  margin: 8px 0 0;
  font-size: 18px;
  font-variant-numeric: tabular-nums;
}
.key-actions {
  display: flex;
  gap: 14px;
  align-items: center;
}
.key-actions button {
  font-size: 13px;
}
.danger {
  color: var(--danger);
}
.delete-confirm {
  background: var(--danger);
}
.key-form {
  display: grid;
  gap: 18px;
}
.key-form :deep(input) {
  width: 100%;
}
.key-form p {
  margin: 0;
}
.empty {
  text-align: center;
  padding: 30px 0;
  color: var(--muted);
}
@media (max-width: 900px) {
  .key-row {
    grid-template-columns: 1fr;
    gap: 20px;
  }
  .key-actions {
    justify-content: flex-end;
  }
}
@media (max-width: 600px) {
  .keys-panel {
    padding: 18px;
  }
  .key-row {
    padding: 16px;
  }
  dl {
    grid-template-columns: 1fr 1fr;
  }
}
</style>
