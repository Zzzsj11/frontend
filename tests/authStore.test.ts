import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useAuthStore } from '../src/stores/auth'

describe('auth logout cleanup', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('clears per-user sidebar keys and the pending digital human draft on logout', async () => {
    const auth = useAuthStore()
    auth.user = {
      id: 'u1',
      username: 'u1',
      displayName: 'U1',
      role: 'user',
      mustChangePassword: false,
    }
    localStorage.setItem('mv_sidebar_song_u1', 'song-a')
    localStorage.setItem('mv_sidebar_task_u1', 'task-a1')
    localStorage.setItem('mv_sidebar_song_other', 'song-b')
    localStorage.setItem('mv:pending-dh', '{}')

    vi.spyOn(globalThis, 'fetch').mockImplementation(
      async () =>
        new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } }),
    )

    await auth.logout()
    expect(auth.user).toBeNull()
    expect(auth.balance).toBeNull()
    // 当前用户的侧边栏选中态与数字人草稿被清理
    expect(localStorage.getItem('mv_sidebar_song_u1')).toBeNull()
    expect(localStorage.getItem('mv_sidebar_task_u1')).toBeNull()
    expect(localStorage.getItem('mv:pending-dh')).toBeNull()
    // 其它用户的记录不受影响
    expect(localStorage.getItem('mv_sidebar_song_other')).toBe('song-b')
  })
})
