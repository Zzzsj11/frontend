import { createRouter, createWebHistory } from 'vue-router'
import App from './App.vue'
import LoginView from './views/LoginView.vue'
import AdminConsoleView from './views/AdminConsoleView.vue'
import ChangePasswordView from './views/ChangePasswordView.vue'
import { useAuthStore } from './stores/auth'
export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', component: LoginView, meta: { public: true } },
    { path: '/projects/:projectId?/:taskId?', component: App },
    { path: '/admin/users', redirect: '/admin' },
    { path: '/admin', component: AdminConsoleView, meta: { admin: true } },
    { path: '/account/password', component: ChangePasswordView },
    { path: '/', redirect: '/projects' },
  ],
})
router.beforeEach(async (to) => {
  const auth = useAuthStore()
  await auth.initialize()
  if (!to.meta.public && !auth.authenticated)
    return { path: '/login', query: { redirect: to.fullPath } }
  if (
    to.meta.admin &&
    !auth.user?.isSuperAdmin &&
    !auth.user?.permissions?.includes('song_emotions.read')
  )
    return '/projects'
  if (to.path === '/login' && auth.authenticated) return '/projects'
})
