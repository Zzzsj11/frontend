<script setup lang="ts">
import { useRouter } from 'vue-router'
import { useAuthStore } from './stores/auth'
import ErrorDialog from './components/ErrorDialog.vue'
const auth = useAuthStore(); const router = useRouter()
const logout = async () => { await auth.logout(); await router.replace('/login') }
</script>
<template><ErrorDialog/><div v-if="!auth.ready" class="boot">正在加载…</div><template v-else><div v-if="auth.authenticated" class="account-bar"><RouterLink v-if="auth.user?.role==='admin'" to="/admin/users">用户管理</RouterLink><span>{{ auth.user?.displayName || auth.user?.username }}</span><RouterLink v-if="auth.user?.mustChangePassword" class="password-warning" to="/account/password">请尽快修改初始密码</RouterLink><button @click="logout">退出登录</button></div><RouterView /></template></template>
<style scoped>.boot{min-height:100vh;display:grid;place-items:center;color:#777}.account-bar{position:fixed;z-index:500;right:22px;top:6px;display:flex;align-items:center;gap:10px;font-size:12px}.account-bar button{border:0;background:none;color:#e65b30;cursor:pointer}.password-warning{color:#d88a00}</style>
