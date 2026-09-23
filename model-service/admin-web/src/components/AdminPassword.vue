<script setup lang="ts">
import { ref } from 'vue'
import { useControl } from '../stores/control'
const store = useControl()
const current = ref('')
const password = ref('')
const confirmation = ref('')
async function submit() {
  await store.changePassword(current.value, password.value, confirmation.value)
  current.value = password.value = confirmation.value = ''
}
</script>
<template>
  <section class="card password">
    <h3>修改管理员密码</h3>
    <p class="muted">新密码至少 8 位，包含字母和数字。修改后所有管理会话需重新登录。</p>
    <form @submit.prevent="submit">
      <label
        >原密码<input
          v-model="current"
          required
          type="password"
          maxlength="128"
          autocomplete="current-password"
      /></label>
      <label
        >新密码<input
          v-model="password"
          required
          type="password"
          minlength="8"
          maxlength="128"
          pattern="(?=.*[A-Za-z])(?=.*[0-9]).{8,128}"
          title="至少 8 位，包含字母和数字"
          autocomplete="new-password"
      /></label>
      <label
        >确认新密码<input
          v-model="confirmation"
          required
          type="password"
          minlength="8"
          maxlength="128"
          autocomplete="new-password"
      /></label>
      <p v-if="store.error" role="alert" class="error">{{ store.error }}</p>
      <button :disabled="store.loading">保存新密码</button>
    </form>
  </section>
</template>
<style scoped>
.password {
  max-width: 440px;
}
form {
  display: grid;
  gap: 16px;
}
</style>
