import { beforeEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { router } from '../../src/router'
import { useAuthStore } from '../../src/stores/auth'

describe('管理台入口权限', () => {
  beforeEach(async () => {
    setActivePinia(createPinia())
    const auth = useAuthStore()
    auth.ready = true
    auth.user = {
      id: 'router-user',
      username: 'router-user',
      displayName: 'Router User',
      role: 'admin',
      mustChangePassword: false,
      isSuperAdmin: false,
      permissions: [],
    }
    await router.push('/projects')
  })

  it.each(['storyboard_options.read', 'song_emotions.read'])(
    '允许只有 %s 的管理员进入',
    async (permission) => {
      const auth = useAuthStore()
      auth.user!.permissions = [permission]
      expect(auth.canAccessAdmin).toBe(true)
      await router.push('/admin')
      expect(router.currentRoute.value.path).toBe('/admin')
    },
  )

  it('没有导航对应权限时回到项目页', async () => {
    expect(useAuthStore().canAccessAdmin).toBe(false)
    await router.push('/admin')
    expect(router.currentRoute.value.path).toBe('/projects')
  })
})
