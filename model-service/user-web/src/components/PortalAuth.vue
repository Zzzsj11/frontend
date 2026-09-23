<script setup lang="ts">
import { ref, watch } from 'vue'
import { usePortal } from '../stores/portal'
const store = usePortal()
const storageKey = 'model-portal.remembered-username'
function readUsername() {
  try {
    const value = localStorage.getItem(storageKey) || ''
    return /^[A-Za-z0-9_\-]+(\.[A-Za-z0-9_\-]+)*$/.test(value) ? value : ''
  } catch {
    return ''
  }
}
const emailName = ref(readUsername())
const remember = ref(!!emailName.value)
const password = ref('')
const newPassword = ref('')
const confirmation = ref('')
const passwordPattern = '(?=.*[A-Za-z])(?=.*[0-9]).{8,128}'
watch(remember, (value) => {
  if (!value) saveUsername(false)
})
function saveUsername(enabled: boolean) {
  try {
    if (enabled) localStorage.setItem(storageKey, emailName.value.toLowerCase())
    else localStorage.removeItem(storageKey)
  } catch {
    /* 浏览器禁用存储时仍可正常登录。 */
  }
}
async function submit() {
  await store.auth(emailName.value.toLowerCase() + '@star-net.cn', password.value)
  password.value = ''
  if (store.user) saveUsername(remember.value)
}
async function changePassword() {
  await store.changePassword(password.value, newPassword.value, confirmation.value)
  password.value = newPassword.value = confirmation.value = ''
}
</script>
<template>
  <section class="card auth">
    <template v-if="store.user?.must_change_password">
      <h2>首次登录，请修改密码</h2>
      <p class="muted">至少 8 位，包含字母和数字。</p>
      <form @submit.prevent="changePassword">
        <label
          >原密码<input
            v-model="password"
            type="password"
            required
            minlength="8"
            maxlength="128"
            autocomplete="current-password"
        /></label>
        <label
          >新密码<input
            v-model="newPassword"
            type="password"
            required
            minlength="8"
            maxlength="128"
            :pattern="passwordPattern"
            title="至少 8 位，包含字母和数字"
            autocomplete="new-password"
        /></label>
        <label
          >确认新密码<input
            v-model="confirmation"
            type="password"
            required
            minlength="8"
            maxlength="128"
            autocomplete="new-password"
        /></label>
        <p v-if="store.error" class="error" role="alert">{{ store.error }}</p>
        <button :disabled="store.loading">更新密码</button>
      </form>
    </template>
    <template v-else>
      <h2>企业邮箱登录</h2>
      <form @submit.prevent="submit">
        <label
          >企业邮箱<span class="email-account"
            ><input
              v-model="emailName"
              aria-label="企业邮箱前缀"
              required
              maxlength="68"
              autocomplete="username"
              pattern="[A-Za-z0-9_\-]+(\.[A-Za-z0-9_\-]+)*"
              placeholder="star-net"
            /><span>@star-net.cn</span></span
          ></label
        >
        <label
          >密码<input
            v-model="password"
            required
            type="password"
            minlength="8"
            maxlength="128"
            autocomplete="current-password"
        /></label>
        <label class="remember"><input v-model="remember" type="checkbox" />记住用户名</label>
        <p v-if="store.error" class="error" role="alert">{{ store.error }}</p>
        <p v-else-if="store.message" role="status">{{ store.message }}</p>
        <button :disabled="store.loading">登录</button>
      </form>
    </template>
  </section>
</template>
<style scoped>
.auth {
  max-width: 380px;
  margin: 50px auto;
}
form {
  display: grid;
  gap: 16px;
  margin-top: 20px;
}
.remember {
  display: flex;
  align-items: center;
  gap: 8px;
}
.remember input {
  width: auto;
  margin: 0;
  accent-color: var(--primary);
}
</style>
