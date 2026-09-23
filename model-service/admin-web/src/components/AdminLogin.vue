<script setup lang="ts">
import { ref } from 'vue'
import { useControl } from '../stores/control'
const store = useControl()
const username = ref('admin')
const password = ref('')
async function login() {
  await store.login(username.value, password.value)
  password.value = ''
}
</script>
<template>
  <main class="login card">
    <p class="eyebrow">INTERNAL MODEL PLATFORM</p>
    <h1>模型服务管理台</h1>
    <p>统一查看模型任务、调用方与测试用量。</p>
    <form @submit.prevent="login">
      <label>用户名<input v-model="username" autocomplete="username" required /></label>
      <label
        >密码<input
          v-model="password"
          type="password"
          autocomplete="current-password"
          required
          maxlength="128"
      /></label>
      <p v-if="store.error" role="alert" class="error">{{ store.error }}</p>
      <p v-else-if="store.message" role="status">{{ store.message }}</p>
      <button :disabled="store.loading">登录</button>
    </form>
  </main>
</template>
<style scoped>
.login {
  max-width: 420px;
  margin: 100px auto;
}
form {
  display: grid;
  gap: 16px;
}
</style>
