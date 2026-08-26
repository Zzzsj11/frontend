<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import DeploymentBadge from './DeploymentBadge.vue'

const auth = useAuthStore()
const router = useRouter()
const menuOpen = ref(false)
const menu = ref<HTMLElement | null>(null)
const userName = computed(() => auth.user?.displayName || auth.user?.username || '用户')
const userInitial = computed(() => userName.value.trim().charAt(0).toUpperCase() || 'U')
const yingheBalance = computed(() => auth.balance?.providers?.yinghe ?? auth.balance)
const ppioBalance = computed(() => auth.balance?.providers?.ppio)
const hasAdminAccess = computed(
  () => auth.user?.isSuperAdmin || Boolean(auth.user?.permissions?.length),
)
const keyText = computed(() => {
  const key = yingheBalance.value?.key
  if (!key) return ''
  return `${key.keyMasked} 余 ${key.remainingDisplay}`
})
const balanceTitle = computed(() => {
  if (yingheBalance.value?.message) return yingheBalance.value.message
  const key = yingheBalance.value?.key
  if (!key) return '点击刷新余额'
  const name = key.keyName ? `（${key.keyName}）` : ''
  const quota = key.quotaAmt == null ? '不限额' : key.quotaAmt
  return `当前 Key ${key.keyMasked}${name} · 月度已用 ${key.usedAmt ?? '--'} / 限额 ${quota} · 点击刷新余额`
})
const ppioBalanceTitle = computed(() => {
  const balance = ppioBalance.value
  if (!balance) return 'PPIO 余额暂不可用'
  if (balance.message) return balance.message
  const details = balance.details
  return `PPIO 可用总额 ¥${balance.balanceDisplay} · 模型额度 ¥${details?.modelCreditBalance ?? '--'} · 账户可用 ¥${details?.accountAvailableBalance ?? '--'}（现金 ¥${details?.cashBalance ?? '--'} + 信用额度 ¥${details?.creditLimit ?? '--'}）· 待入账 ¥${details?.pendingCharges ?? '--'} · 未结账单 ¥${details?.outstandingInvoices ?? '--'} · 点击刷新`
})

const logout = async () => {
  menuOpen.value = false
  await auth.logout()
  await router.replace('/login')
}
const closeFromOutside = (event: MouseEvent) => {
  if (menu.value && !menu.value.contains(event.target as Node)) menuOpen.value = false
}
const closeFromEscape = (event: KeyboardEvent) => {
  if (event.key === 'Escape') menuOpen.value = false
}
const refreshBalance = () => {
  if (!auth.user?.mustChangePassword) void auth.loadBalance(true)
}
let refreshTimer = 0
onMounted(() => {
  document.addEventListener('click', closeFromOutside)
  document.addEventListener('keydown', closeFromEscape)
  window.addEventListener('focus', refreshBalance)
  refreshTimer = window.setInterval(refreshBalance, 60_000)
  if (!auth.balance) refreshBalance()
})
onBeforeUnmount(() => {
  document.removeEventListener('click', closeFromOutside)
  document.removeEventListener('keydown', closeFromEscape)
  window.removeEventListener('focus', refreshBalance)
  window.clearInterval(refreshTimer)
})
</script>

<template>
  <header class="app-header">
    <RouterLink class="brand" to="/projects" aria-label="返回镜序 MV 工作台">
      <span class="brand-mark" aria-hidden="true">↗</span>
      <span class="brand-name">镜序 MV 工作台</span>
      <span class="beta">内测版</span>
    </RouterLink>
    <div class="header-actions">
      <DeploymentBadge />
      <button
        class="balance-pill yinghe"
        :class="{ loading: auth.balanceLoading }"
        :title="balanceTitle"
        @click="refreshBalance"
      >
        <span class="balance-icon" aria-hidden="true">ϟ</span>
        <span class="balance-provider">英和</span>
        <span class="balance-value">{{ yingheBalance?.balanceDisplay || '--' }}</span>
        <span v-if="keyText" class="balance-key" data-test="key-quota">{{ keyText }}</span>
      </button>
      <button
        class="balance-pill ppio"
        :class="{ loading: auth.balanceLoading }"
        :title="ppioBalanceTitle"
        data-test="ppio-balance"
        @click="refreshBalance"
      >
        <span class="balance-icon" aria-hidden="true">P</span>
        <span class="balance-provider">PPIO</span>
        <span class="balance-value">{{ ppioBalance?.balanceDisplay || '--' }}</span>
      </button>
      <div ref="menu" class="user-menu">
        <button
          class="user-trigger"
          :aria-expanded="menuOpen"
          aria-haspopup="menu"
          @click.stop="menuOpen = !menuOpen"
        >
          <span class="user-name">{{ userName }}</span>
          <span class="user-avatar">{{ userInitial }}</span>
          <span class="chevron" :class="{ open: menuOpen }">⌄</span>
        </button>
        <div v-if="menuOpen" class="user-dropdown" role="menu">
          <div class="user-summary">
            <strong>{{ userName }}</strong
            ><span>@{{ auth.user?.username }}</span>
          </div>
          <RouterLink v-if="hasAdminAccess" role="menuitem" to="/admin" @click="menuOpen = false"
            >管理后台</RouterLink
          >
          <RouterLink role="menuitem" to="/account/password" @click="menuOpen = false"
            >修改密码</RouterLink
          >
          <p v-if="auth.user?.mustChangePassword" class="password-warning">请尽快修改初始密码</p>
          <button class="logout" role="menuitem" @click="logout">退出登录</button>
        </div>
      </div>
    </div>
  </header>
</template>

<style scoped>
.app-header {
  position: relative;
  z-index: 600;
  display: flex;
  flex: 0 0 auto;
  align-items: center;
  justify-content: space-between;
  height: 58px;
  margin: 10px 14px 0;
  padding: 0 12px 0 10px;
  border: 1px solid #eaded4;
  border-radius: var(--radius-lg);
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.99), rgba(255, 248, 242, 0.96));
  box-shadow:
    0 8px 24px rgba(91, 64, 42, 0.07),
    inset 0 1px 0 #fff;
}
.brand {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 10px;
  color: #201c19;
  text-decoration: none;
}
.brand-mark {
  display: grid;
  width: 34px;
  height: 34px;
  place-items: center;
  border-radius: var(--radius-md);
  background: var(--primary-gradient);
  color: #fff;
  font-size: 20px;
  font-weight: 700;
  box-shadow: 0 5px 12px rgba(255, 100, 39, 0.2);
}
.brand-name {
  font-size: 16px;
  font-weight: 750;
  letter-spacing: 0.01em;
}
.beta {
  padding: 3px 7px;
  border-radius: var(--radius-sm);
  background: var(--primary-light);
  color: var(--primary);
  font-size: 10px;
  font-weight: 650;
}
.header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}
.balance-pill,
.user-trigger {
  height: 38px;
  border: 1px solid #ebded4;
  border-radius: var(--radius-md);
  background: rgba(255, 255, 255, 0.92);
  box-shadow: inset 0 1px 0 #fff;
  color: #4d4239;
  cursor: pointer;
}
.balance-pill {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 0 12px;
  font: inherit;
}
.balance-pill:hover,
.user-trigger:hover {
  border-color: #f0b28f;
  background: #fff;
}
.balance-pill.loading {
  opacity: 0.65;
}
.balance-icon {
  display: grid;
  width: 21px;
  height: 21px;
  place-items: center;
  border-radius: 50%;
  background: var(--primary-light);
  color: var(--primary);
  font-size: 15px;
  font-weight: 800;
}
.balance-value {
  min-width: 48px;
  text-align: right;
  font-size: 13px;
  font-weight: 650;
  font-variant-numeric: tabular-nums;
}
.balance-provider {
  color: var(--text-secondary);
  font-size: 11px;
  font-weight: 650;
}
.balance-pill.ppio .balance-icon {
  background: var(--success-light);
  color: var(--success);
  font-size: 11px;
}
.balance-key {
  padding-left: 7px;
  border-left: 1px solid #f0e4d9;
  color: #a09186;
  font-size: 11px;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
.user-menu {
  position: relative;
}
.user-trigger {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 0 7px 0 12px;
  font: inherit;
}
.user-name {
  max-width: 100px;
  overflow: hidden;
  font-size: 13px;
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.user-avatar {
  display: grid;
  width: 28px;
  height: 28px;
  place-items: center;
  border-radius: 50%;
  background: var(--primary-gradient);
  color: #fff;
  font-size: var(--font-sm);
  font-weight: 700;
  box-shadow: 0 3px 9px rgba(255, 94, 36, 0.18);
}
.chevron {
  margin-right: 2px;
  color: #a08775;
  font-size: 13px;
  transition: transform 0.15s;
}
.chevron.open {
  transform: rotate(180deg);
}
.user-dropdown {
  position: absolute;
  top: 46px;
  right: 0;
  display: flex;
  width: 190px;
  flex-direction: column;
  padding: 8px;
  border: 1px solid #eadfd6;
  border-radius: var(--radius-lg);
  background: #fff;
  box-shadow: var(--shadow-dropdown);
}
.user-summary {
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin: 0 4px 6px;
  padding: 7px 7px 10px;
  border-bottom: 1px solid #f1e9e3;
}
.user-summary strong {
  font-size: 13px;
}
.user-summary span {
  color: #a09186;
  font-size: 11px;
}
.user-dropdown a,
.logout {
  padding: 9px 11px;
  border: 0;
  border-radius: var(--radius-sm);
  background: transparent;
  color: #4a4038;
  text-align: left;
  text-decoration: none;
  font: inherit;
  font-size: 13px;
  cursor: pointer;
}
.user-dropdown a:hover,
.logout:hover {
  background: var(--primary-light);
  color: var(--primary);
}
.logout {
  color: #d64b3f;
}
.password-warning {
  margin: 4px;
  padding: 7px 9px;
  border-radius: var(--radius-sm);
  background: var(--warning-light);
  color: var(--warning);
  font-size: 11px;
  line-height: 1.45;
}
@media (max-width: 640px) {
  .app-header {
    margin: 6px 8px 0;
  }
  .brand-name {
    font-size: var(--font-md);
  }
  .beta,
  .user-name {
    display: none;
  }
  .balance-pill {
    padding: 0 8px;
  }
  .balance-value {
    min-width: 38px;
  }
  .balance-key {
    display: none;
  }
}
</style>
