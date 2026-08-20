<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import AppIcon from './AppIcon.vue'
import DeploymentBadge from './DeploymentBadge.vue'
import { useAuthStore } from '../stores/auth'

defineProps<{ groupTitle: string; title: string; loading?: boolean }>()
const emit = defineEmits<{ refresh: [] }>()
const auth = useAuthStore()
const router = useRouter()
const menuOpen = ref(false)
const menu = ref<HTMLElement | null>(null)
const userName = computed(() => auth.user?.displayName || auth.user?.username || '管理员')
const userInitial = computed(() => userName.value.trim().charAt(0).toUpperCase() || 'A')

const logout = async () => {
  menuOpen.value = false
  await auth.logout()
  await router.replace('/login')
}
const closeOutside = (event: MouseEvent) => {
  if (menu.value && !menu.value.contains(event.target as Node)) menuOpen.value = false
}
const closeEscape = (event: KeyboardEvent) => {
  if (event.key === 'Escape') menuOpen.value = false
}
onMounted(() => {
  document.addEventListener('click', closeOutside)
  document.addEventListener('keydown', closeEscape)
})
onBeforeUnmount(() => {
  document.removeEventListener('click', closeOutside)
  document.removeEventListener('keydown', closeEscape)
})
</script>

<template>
  <header class="admin-topbar">
    <div class="page-identity">
      <p>{{ groupTitle }}</p>
      <h1>{{ title }}</h1>
    </div>
    <div class="topbar-actions">
      <DeploymentBadge />
      <RouterLink class="icon-button" to="/projects" title="返回工作台" aria-label="返回工作台">
        <AppIcon name="home" :size="18" />
      </RouterLink>
      <button class="refresh-button" type="button" :disabled="loading" @click="emit('refresh')">
        {{ loading ? '刷新中…' : '刷新' }}
      </button>
      <div ref="menu" class="admin-user-menu">
        <button
          type="button"
          class="admin-user-trigger"
          :aria-expanded="menuOpen"
          aria-haspopup="menu"
          @click.stop="menuOpen = !menuOpen"
        >
          <span class="admin-avatar">{{ userInitial }}</span>
          <span class="admin-user-copy"
            ><b>{{ userName }}</b
            ><small>管理员</small></span
          >
          <AppIcon
            name="chevron-right"
            :size="13"
            class="menu-chevron"
            :class="{ open: menuOpen }"
          />
        </button>
        <div v-if="menuOpen" class="admin-user-dropdown" role="menu">
          <RouterLink role="menuitem" to="/account/password" @click="menuOpen = false"
            >修改密码</RouterLink
          >
          <button type="button" role="menuitem" class="logout" @click="logout">退出登录</button>
        </div>
      </div>
    </div>
  </header>
</template>

<style scoped>
.admin-topbar {
  position: relative;
  z-index: 500;
  display: flex;
  min-height: 64px;
  flex: 0 0 auto;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  padding: 0 28px;
  border-bottom: 1px solid #e4e7ec;
  background: rgba(255, 255, 255, 0.96);
  box-shadow: 0 1px 2px rgba(16, 24, 40, 0.03);
}
.page-identity p {
  margin: 0 0 2px;
  color: #667085;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.08em;
}
.page-identity h1 {
  margin: 0;
  color: #1d2939;
  font-size: 20px;
  line-height: 1.2;
}
.topbar-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}
.icon-button,
.refresh-button,
.admin-user-trigger {
  border: 1px solid #dfe3e8;
  border-radius: 7px;
  background: #fff;
  color: #475467;
}
.icon-button {
  display: grid;
  width: 34px;
  height: 34px;
  place-items: center;
  text-decoration: none;
}
.icon-button:hover,
.refresh-button:hover:not(:disabled),
.admin-user-trigger:hover {
  border-color: #ffb18f;
  color: var(--primary);
}
.refresh-button {
  height: 34px;
  padding: 0 13px;
  font: inherit;
  font-size: 12px;
  cursor: pointer;
}
.refresh-button:disabled {
  cursor: wait;
  opacity: 0.6;
}
.admin-user-menu {
  position: relative;
}
.admin-user-trigger {
  display: flex;
  min-width: 138px;
  height: 40px;
  align-items: center;
  gap: 8px;
  padding: 0 8px;
  font: inherit;
  text-align: left;
  cursor: pointer;
}
.admin-avatar {
  display: grid;
  width: 27px;
  height: 27px;
  place-items: center;
  border-radius: 6px;
  background: #344054;
  color: #fff;
  font-size: 12px;
  font-weight: 700;
}
.admin-user-copy {
  display: flex;
  min-width: 0;
  flex: 1;
  flex-direction: column;
  line-height: 1.15;
}
.admin-user-copy b {
  max-width: 92px;
  overflow: hidden;
  color: #344054;
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.admin-user-copy small {
  color: #98a2b3;
  font-size: 10px;
}
.menu-chevron {
  color: #98a2b3;
  transform: rotate(90deg);
  transition: transform 0.15s;
}
.menu-chevron.open {
  transform: rotate(-90deg);
}
.admin-user-dropdown {
  position: absolute;
  top: 46px;
  right: 0;
  display: flex;
  width: 156px;
  flex-direction: column;
  padding: 6px;
  border: 1px solid #e4e7ec;
  border-radius: 8px;
  background: #fff;
  box-shadow: 0 12px 28px rgba(16, 24, 40, 0.14);
}
.admin-user-dropdown a,
.admin-user-dropdown button {
  padding: 9px 10px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: #344054;
  font: inherit;
  font-size: 12px;
  text-align: left;
  text-decoration: none;
  cursor: pointer;
}
.admin-user-dropdown a:hover,
.admin-user-dropdown button:hover {
  background: #f2f4f7;
}
.admin-user-dropdown .logout {
  color: #d92d20;
}
@media (max-width: 720px) {
  .admin-topbar {
    min-height: 58px;
    padding: 0 14px;
  }
  .page-identity p,
  .admin-user-copy {
    display: none;
  }
  .page-identity h1 {
    font-size: 17px;
  }
  .admin-user-trigger {
    min-width: 0;
    width: 40px;
  }
  .menu-chevron {
    display: none;
  }
}
</style>
