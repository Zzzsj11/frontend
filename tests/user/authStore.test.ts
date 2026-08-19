import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useAuthStore } from '../../src/stores/auth'
import { useProjectStore } from '../../src/stores/project'
import type { ScriptLine, SongProject } from '../../src/types'

describe('auth logout cleanup', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('does not load business data before a temporary-password user changes password', async () => {
    const auth = useAuthStore()
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({
          accessToken: 'temporary-token',
          user: {
            id: 'forced-user',
            username: 'forced-user',
            displayName: 'Forced User',
            role: 'user',
            mustChangePassword: true,
          },
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    )

    await auth.login('forced-user', 'temporary-password')

    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(fetchMock.mock.calls[0]?.[0]).toBe('/api/auth/login')
    expect(auth.balance).toBeNull()
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

  it('clears the in-memory workspace on logout so the next account sees no residue', async () => {
    const auth = useAuthStore()
    const project = useProjectStore()
    auth.user = {
      id: 'u1',
      username: 'u1',
      displayName: 'U1',
      role: 'user',
      mustChangePassword: false,
    }
    // 模拟老账号的工作区现场
    project.ownerUserId = 'u1'
    project.songProjects = [{ id: 'song-a', name: '老账号项目', tasks: [] } as SongProject]
    project.lines = [{ id: 'l1' } as ScriptLine]
    project.activeSongId = 'song-a'
    project.activeTaskId = 'task-a1'

    vi.spyOn(globalThis, 'fetch').mockImplementation(
      async () =>
        new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } }),
    )

    await auth.logout()
    expect(project.songProjects).toEqual([])
    expect(project.lines).toEqual([])
    expect(project.activeSongId).toBe('')
    expect(project.activeTaskId).toBeNull()
  })
})
