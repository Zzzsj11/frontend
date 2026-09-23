<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import ApiDocs from './ApiDocs.vue'
import PortalAuth from './PortalAuth.vue'
import UserKeys from './UserKeys.vue'
import PointsAccount from './PointsAccount.vue'
import { usePortal } from '../stores/portal'
import { prettyPoints } from '../utils/financial'
const store = usePortal()
const section = ref('api')
watch(
  () => store.user?.id,
  (id, previous) => {
    if (id && id !== previous) section.value = 'account'
  },
)
async function showApi() {
  section.value = 'api'
  await store.loadModels()
}
onMounted(() => store.loadModels())
</script>
<template>
  <div class="portal-shell">
    <header class="portal-header">
      <div class="brand">
        <p class="eyebrow">ALL IN ONE MODEL API</p>
        <h1>模型中控台</h1>
      </div>
      <nav aria-label="用户导航">
        <button
          v-if="store.user && !store.user.must_change_password"
          :class="{ secondary: section !== 'account' }"
          @click="section = 'account'"
        >
          积分账户</button
        ><button
          v-if="!store.user?.must_change_password"
          :class="{ secondary: section !== 'api' }"
          @click="showApi"
        >
          API
        </button>
      </nav>
      <div class="account-actions">
        <span v-if="store.user?.quota" class="balance-pill"
          >可用积分 <strong>{{ prettyPoints(store.user.quota.available_points) }}</strong></span
        ><button v-if="!store.user" class="secondary" @click="section = 'auth'">企业邮箱登录</button
        ><button v-else class="secondary" @click="store.logout">退出登录</button>
      </div>
    </header>
    <main>
      <p
        v-if="
          store.error && !store.user?.must_change_password && (section === 'api' || !!store.user)
        "
        class="error"
        role="alert"
      >
        {{ store.error }}
      </p>
      <p
        v-if="
          store.message && !store.user?.must_change_password && (section === 'api' || !!store.user)
        "
        role="status"
      >
        {{ store.message }}
      </p>
      <PortalAuth v-if="store.user?.must_change_password || (section !== 'api' && !store.user)" />
      <template v-else-if="section === 'api'"><UserKeys v-if="store.user" /><ApiDocs /></template>
      <PointsAccount v-else-if="store.user" />
    </main>
  </div>
</template>
<style scoped>
.portal-header {
  display: flex;
  align-items: center;
  gap: 36px;
  padding: 20px 32px;
  background: var(--panel);
  border-bottom: 1px solid var(--border);
  flex-wrap: wrap;
}
.brand h1 {
  font-size: 22px;
  margin: 0;
}
.brand .eyebrow {
  margin: 0 0 6px;
  font-size: 10px;
}
nav,
.account-actions {
  display: flex;
  gap: 10px;
  align-items: center;
}
.account-actions {
  margin-left: auto;
}
.balance-pill {
  font-size: 13px;
  color: var(--primary);
  background: var(--primary-light);
  padding: 10px 14px;
  border-radius: var(--radius-sm);
}
.balance-pill strong {
  margin-left: 6px;
}
main {
  max-width: 1240px;
  padding: 32px 24px 60px;
  margin: auto;
}
main > :deep(.card) {
  margin-bottom: 24px;
}
@media (max-width: 600px) {
  .portal-header {
    padding: 18px 16px;
    gap: 16px;
  }
  nav {
    order: 3;
    width: 100%;
  }
  nav button {
    flex: 1;
  }
  .account-actions {
    gap: 8px;
  }
  .balance-pill {
    display: none;
  }
  main {
    padding: 24px 16px 40px;
  }
}
</style>
