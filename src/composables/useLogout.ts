import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'

export function useLogout() {
  const auth = useAuthStore()
  const router = useRouter()
  const loggingOut = ref(false)
  async function logout() {
    if (loggingOut.value) return
    loggingOut.value = true
    try {
      await auth.logout()
    } catch {
      // 登录页显示待注销状态和重试入口。
    } finally {
      loggingOut.value = false
    }
    await router.replace('/login')
  }
  return { logout, loggingOut }
}
