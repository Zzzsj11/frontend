<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'
const auth = useAuthStore(),
  route = useRoute(),
  router = useRouter()
const username = ref(''),
  password = ref(''),
  error = ref('')
const submit = async () => {
  error.value = ''
  try {
    await auth.login(username.value.trim(), password.value)
    await router.replace(String(route.query.redirect || '/projects'))
  } catch (value) {
    error.value = value instanceof Error ? value.message : '登录失败'
  }
}
</script>
<template>
  <main class="login-page">
    <form class="login-card" @submit.prevent="submit">
      <h1>镜序 MV 工作台</h1>
      <p>登录后管理你的项目、角色和视频</p>
      <label>用户名<input v-model="username" autocomplete="username" required /></label
      ><label
        >密码<input v-model="password" type="password" autocomplete="current-password" required
      /></label>
      <p v-if="error" class="error">{{ error }}</p>
      <button :disabled="auth.loading">{{ auth.loading ? '登录中…' : '登录' }}</button>
    </form>
  </main>
</template>
<style scoped>
.login-page {
  min-height: 100vh;
  display: grid;
  place-items: center;
  background: radial-gradient(circle at top, var(--primary-light), #f5f6fa 55%);
}
.login-card {
  width: 360px;
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 34px;
  border-radius: var(--radius-pill);
  background: #fff;
  box-shadow: 0 18px 60px rgba(40, 30, 20, 0.14);
}
h1 {
  margin: 0;
  color: var(--primary-hover);
}
p {
  margin: 0;
  color: var(--text-secondary);
}
label {
  display: flex;
  flex-direction: column;
  gap: 7px;
  font-size: 13px;
  font-weight: 600;
}
input {
  padding: 11px 12px;
  border: 1px solid var(--border-dark);
  border-radius: var(--radius-sm);
  font: inherit;
}
button {
  padding: 11px;
  border: 0;
  border-radius: var(--radius-pill);
  background: var(--primary-hover);
  color: #fff;
  font-weight: 700;
  cursor: pointer;
}
.error {
  color: var(--danger);
  font-size: 13px;
}
</style>
