<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { apiRequest } from '../api/client'
interface UserRow {
  id: string
  username: string
  displayName: string
  role: string
  status: string
}
const users = ref<UserRow[]>([]),
  username = ref(''),
  displayName = ref(''),
  password = ref(''),
  error = ref('')
const load = async () => {
  users.value = await apiRequest<UserRow[]>('/admin/users')
}
const create = async () => {
  error.value = ''
  try {
    await apiRequest('/admin/users', {
      method: 'POST',
      body: JSON.stringify({
        username: username.value,
        password: password.value,
        display_name: displayName.value,
        role: 'user',
      }),
    })
    username.value = ''
    displayName.value = ''
    password.value = ''
    await load()
  } catch (value) {
    error.value = value instanceof Error ? value.message : '创建失败'
  }
}
const disable = async (user: UserRow) => {
  await apiRequest(`/admin/users/${user.id}`, {
    method: 'PATCH',
    body: JSON.stringify({ status: user.status === 'active' ? 'disabled' : 'active' }),
  })
  await load()
}
onMounted(load)
</script>
<template>
  <main class="admin">
    <header>
      <div>
        <h1>用户管理</h1>
        <p>创建用户并控制账号状态</p>
      </div>
      <RouterLink to="/projects">返回工作台</RouterLink>
    </header>
    <form @submit.prevent="create">
      <input v-model="username" placeholder="用户名" required minlength="3" /><input
        v-model="displayName"
        placeholder="显示名称"
      /><input
        v-model="password"
        type="password"
        placeholder="初始密码（至少 8 位）"
        required
        minlength="8"
      /><button>创建用户</button>
    </form>
    <p v-if="error" class="error">{{ error }}</p>
    <table>
      <thead>
        <tr>
          <th>用户名</th>
          <th>名称</th>
          <th>角色</th>
          <th>状态</th>
          <th></th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="user in users" :key="user.id">
          <td>{{ user.username }}</td>
          <td>{{ user.displayName }}</td>
          <td>{{ user.role }}</td>
          <td>{{ user.status }}</td>
          <td>
            <button class="link" @click="disable(user)">
              {{ user.status === 'active' ? '禁用' : '启用' }}
            </button>
          </td>
        </tr>
      </tbody>
    </table>
  </main>
</template>
<style scoped>
.admin {
  max-width: 900px;
  margin: 56px auto;
  padding: 28px;
}
header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
h1 {
  margin: 0;
}
p {
  color: var(--text-secondary);
}
form {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr auto;
  gap: 10px;
  margin: 24px 0;
}
input,
button {
  padding: 10px;
  border: 1px solid var(--border-dark);
  border-radius: var(--radius-sm);
}
button {
  background: var(--primary-hover);
  color: white;
  border: 0;
}
table {
  width: 100%;
  border-collapse: collapse;
  background: #fff;
}
th,
td {
  text-align: left;
  padding: 12px;
  border-bottom: 1px solid var(--border);
}
.link {
  padding: 5px 10px;
}
.error {
  color: var(--danger);
}
</style>
