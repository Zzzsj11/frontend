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
      // 请求失败已通过全局错误提示展示，保留页面以便重试。
      return
    } finally {
      loggingOut.value = false
    }
    await router.replace('/login')
  }
  return { logout, loggingOut }
}
