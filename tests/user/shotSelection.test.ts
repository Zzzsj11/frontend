import { beforeEach, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useProjectStore } from '../../src/stores/project'
import * as api from '../../src/api/domain'
import type { ScriptLine } from '../../src/types'

beforeEach(() => setActivePinia(createPinia()))

function workspace() {
  const store = useProjectStore()
  store.activeTaskId = 'task'
  store.lines = [
    {
      id: 'line',
      digitalHumanIds: [],
      voice: { status: 'none' },
      scene: { status: 'none' },
      shot: {
        status: 'done',
        currentAssetId: 'new',
        assets: [
          { id: 'old', coverUrl: 'old.jpg', videoUrl: 'old.mp4', duration: 5 },
          { id: 'new', coverUrl: 'new.jpg', videoUrl: 'new.mp4', duration: 5 },
        ],
      },
    },
  ] as ScriptLine[]
  return store
}

it('saves the selected asset before changing playback or accepting an export', async () => {
  const store = workspace()
  let finish!: (value: { lineId: string; assetId: string }) => void
  vi.spyOn(api, 'selectCurrentShot').mockImplementation(
    () =>
      new Promise((resolve) => {
        finish = resolve
      }),
  )
  const exportVideo = vi.spyOn(api, 'exportVideo')
  const selected = store.selectShotAsset('line', 'old')
  expect(store.lines[0]!.shot.currentAssetId).toBe('new')
  await store.runExport('video')
  expect(exportVideo).not.toHaveBeenCalled()
  finish({ lineId: 'line', assetId: 'old' })
  expect(await selected).toBe(true)
  expect(api.selectCurrentShot).toHaveBeenCalledWith('line', 'old')
  expect(store.lines[0]!.shot.currentAssetId).toBe('old')
  expect(store.lines[0]!.shot.imageUrl).toBe('old.jpg')
  expect(store.shotSelectionPending).toEqual({})
})

it('keeps the old selection on failure and ignores responses after a task switch', async () => {
  const store = workspace()
  vi.spyOn(api, 'selectCurrentShot').mockRejectedValueOnce(new Error('storage unavailable'))
  expect(await store.selectShotAsset('line', 'old')).toBe(false)
  expect(store.lines[0]!.shot.currentAssetId).toBe('new')
  let finish!: (value: { lineId: string; assetId: string }) => void
  vi.mocked(api.selectCurrentShot).mockImplementation(
    () =>
      new Promise((resolve) => {
        finish = resolve
      }),
  )
  const request = store.selectShotAsset('line', 'old')
  store.activeTaskId = 'other-task'
  finish({ lineId: 'line', assetId: 'old' })
  expect(await request).toBe(false)
  expect(store.lines[0]!.shot.currentAssetId).toBe('new')
})
