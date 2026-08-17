import {
  expect,
  request as playwrightRequest,
  test,
  type APIRequestContext,
  type APIResponse,
} from '@playwright/test'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { remoteCredentials, targetBaseURL, testRunId } from '../env'

test.skip(!process.env.REMOTE_API_E2E, 'set REMOTE_API_E2E=1 to test a deployed API')
test.describe.configure({ mode: 'serial' })
test.setTimeout(20 * 60 * 1000)

const baseURL = targetBaseURL()
const { username: adminUsername, password: adminPassword } = remoteCredentials()
const realGeneration = process.env.REMOTE_REAL_GENERATION === '1'
const runId = testRunId()
const assFile =
  process.env.REMOTE_E2E_ASS_FILE ||
  join(process.cwd(), 'test-artifacts/full-journey/inputs/10012204-full-e2e.ass')

async function json<T = Record<string, unknown>>(
  response: APIResponse,
  expected: number | number[] = 200,
): Promise<T> {
  const allowed = Array.isArray(expected) ? expected : [expected]
  expect(allowed, `${response.url()} => ${response.status()} ${await response.text()}`).toContain(
    response.status(),
  )
  return response.json() as Promise<T>
}

async function login(
  username: string,
  password: string,
): Promise<{ api: APIRequestContext; token: string; user: unknown }> {
  const session = await playwrightRequest.newContext({
    baseURL,
    extraHTTPHeaders: { 'X-Test-Run-Id': runId },
  })
  const body = await json(await session.post('/api/auth/login', { data: { username, password } }))
  const token = body.accessToken as string
  expect(token).toBeTruthy()
  const storage = await session.storageState()
  await session.dispose()
  const api = await playwrightRequest.newContext({
    baseURL,
    storageState: storage,
    extraHTTPHeaders: { Authorization: `Bearer ${token}`, 'X-Test-Run-Id': runId },
  })
  return { api, token, user: body.user }
}

test('remote API contract, authorization, isolation and soft-delete journey', async () => {
  const publicApi = await playwrightRequest.newContext({
    baseURL,
    extraHTTPHeaders: { 'X-Test-Run-Id': runId },
  })
  const health = await json(await publicApi.get('/api/health'))
  expect(health).toMatchObject({ ok: true, postgres: true, redis: true })
  expect((await publicApi.get('/api/auth/me')).status()).toBe(401)
  expect(
    (
      await publicApi.post('/api/auth/login', {
        data: { username: adminUsername, password: 'definitely-wrong' },
      })
    ).status(),
  ).toBe(401)

  const adminLogin = await login(adminUsername, adminPassword)
  const admin = adminLogin.api
  let testUserId = ''
  let projectId = ''
  let styleId = ''
  let humanId = ''
  let chatId = ''
  const username = `e2e_${runId
    .replace(/[^a-zA-Z0-9]/g, '')
    .slice(-18)
    .toLowerCase()}`
  const initialPassword = `Remote-${runId.slice(-8)}-A1!`
  const changedPassword = `${initialPassword}x`

  try {
    const me = await json<{ username: string }>(await admin.get('/api/auth/me'))
    expect(me.username).toBe(adminUsername)
    await json(await admin.get('/api/account/balance'))

    const refreshed = await json<{ accessToken: string }>(await admin.post('/api/auth/refresh'))
    expect(refreshed.accessToken).toBeTruthy()

    const createdUser = await json<{ id: string }>(
      await admin.post('/api/admin/users', {
        data: {
          username,
          password: initialPassword,
          display_name: `远程验收 ${runId}`,
          role: 'user',
        },
      }),
      201,
    )
    testUserId = createdUser.id
    await json(
      await admin.patch(`/api/admin/users/${testUserId}`, {
        data: { display_name: `远程验收已更新 ${runId}` },
      }),
    )
    const users = await json<Record<string, unknown>[]>(await admin.get('/api/admin/users'))
    expect(users.some((item) => item.id === testUserId)).toBeTruthy()

    let userLogin = await login(username, initialPassword)
    let user = userLogin.api
    expect((await user.get('/api/admin/users')).status()).toBe(403)
    await json(
      await user.post('/api/auth/change-password', {
        data: { current_password: initialPassword, new_password: changedPassword },
      }),
    )
    await user.dispose()
    userLogin = await login(username, changedPassword)
    user = userLogin.api

    try {
      const createdProject = await json<{ id: string }>(
        await user.post('/api/projects', {
          data: {
            name: `REMOTE-E2E ${runId}`,
            artist: 'Codex',
            song_code: '10012204',
            description: 'remote contract test',
          },
        }),
        201,
      )
      projectId = createdProject.id
      await json(
        await user.patch(`/api/projects/${projectId}`, {
          data: { description: 'remote contract test updated' },
        }),
      )
      expect(
        (await json<Record<string, unknown>[]>(await user.get('/api/projects'))).some(
          (item) => item.id === projectId,
        ),
      ).toBeTruthy()
      expect((await admin.get(`/api/tasks/${projectId}`)).status()).toBe(404)

      const task = await json<{ id: string }>(
        await user.post(`/api/projects/${projectId}/tasks`, {
          data: {
            title: `Manual ${runId}`,
            storyboard_type: 'manual',
            overall_prompt: 'remote API acceptance',
          },
        }),
        201,
      )
      const taskId = task.id
      await json(
        await user.patch(`/api/tasks/${taskId}`, { data: { title: `Manual updated ${runId}` } }),
      )
      await json(await user.get(`/api/tasks/${taskId}`))

      const styles = await json<Record<string, unknown>[]>(
        await user.get('/api/digital-human-styles'),
      )
      expect(styles.length).toBeGreaterThan(0)
      const style = await json<{ id: string }>(
        await user.post('/api/digital-human-styles', { data: { name: `E2E style ${runId}` } }),
        201,
      )
      styleId = style.id

      const upload = await json<{ url: string; thumbnailUrl: string }>(
        await user.post('/api/uploads?category=e2e', {
          multipart: {
            file: {
              name: `avatar-${runId}.png`,
              mimeType: 'image/png',
              buffer: Buffer.from(
                'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=',
                'base64',
              ),
            },
          },
        }),
      )
      expect(upload.url).toMatch(/^https:\/\//)
      expect(upload.thumbnailUrl).toMatch(/^https:\/\//)
      const imported = await json<{ url: string }>(
        await user.post('/api/uploads/import', {
          data: { url: upload.url, category: 'e2e-imports', filename: `import-${runId}.png` },
        }),
      )
      expect(imported.url).toMatch(/^https:\/\//)

      const human = await json<{ id: string }>(
        await user.post('/api/digital-humans', {
          data: {
            name: `E2E human ${runId}`,
            style_id: styleId,
            description: 'remote test character',
            avatar_url: upload.url,
            avatar_thumbnail_url: upload.thumbnailUrl,
            avatar_prompt: 'test portrait',
            gender: 'unknown',
            age_description: 'adult',
            appearance_style: 'realistic',
            clothing_description: 'plain',
            suitable_music_styles: 'all',
            system_prompt: 'remote test only',
            source: 'uploaded',
          },
        }),
        201,
      )
      humanId = human.id
      await json(
        await user.patch(`/api/digital-humans/${humanId}`, {
          data: { description: 'updated remote test character' },
        }),
      )
      expect(
        (await json<Record<string, unknown>[]>(await user.get('/api/digital-humans'))).some(
          (item) => item.id === humanId,
        ),
      ).toBeTruthy()
      await json(
        await user.put(`/api/tasks/${taskId}/cast`, { data: { digital_human_ids: [humanId] } }),
      )

      const line1 = await json<{ id: string }>(
        await user.post(`/api/tasks/${taskId}/storyboard/lines`, {
          data: {
            source: 'manual',
            shot_type: 'character',
            planned_duration: 4,
            lyrics: 'remote line one',
            scene_prompt: 'scene one',
            shot_prompt: 'shot one',
            digital_human_ids: [humanId],
          },
        }),
        201,
      )
      const line2 = await json<{ id: string }>(
        await user.post(`/api/tasks/${taskId}/storyboard/lines`, {
          data: {
            source: 'manual',
            shot_type: 'empty',
            planned_duration: 15,
            lyrics: 'remote line two',
            scene_prompt: 'scene two',
            shot_prompt: 'shot two',
            digital_human_ids: [],
          },
        }),
        201,
      )
      await json(
        await user.patch(`/api/storyboard-lines/${line1.id}`, {
          data: { scene_prompt: 'scene one updated', digital_human_ids: [humanId] },
        }),
      )
      await json(
        await user.post(`/api/tasks/${taskId}/storyboard/reorder`, {
          data: { line_ids: [line2.id, line1.id] },
        }),
      )

      const general = await json<{ lines: unknown[]; taskId: string }>(
        await user.post(`/api/projects/${projectId}/storyboards/general`, {
          data: {
            genre: '流行歌曲',
            secondary_category: '爱情消极',
            tertiary_category: '失恋',
            season: 'autumn',
            gender: '女',
            age_group: 'adult',
            visual_style: 'cinematic',
            ratio: '9:16',
            resolution: '720p',
            image_model: 'gpt-image-2',
            video_model: 'doubao-seedance-2.0',
            empty_shot_count: 1,
            character_shot_count: 1,
            total_duration: 10,
            digital_human_ids: [humanId],
            extra_requirement: 'remote test',
          },
        }),
        201,
      )
      expect(general.lines).toHaveLength(2)
      await json(await user.get(`/api/tasks/${general.taskId}`))
      await json(
        await user.post(`/api/tasks/${general.taskId}/storyboard/retry-failed`, { data: {} }),
      )

      const ass = await json<{ status: string; lines: { id: string }[]; taskId: string }>(
        await user.post('/api/storyboards/ass', {
          multipart: {
            project_id: projectId,
            song_id: '10012204',
            digital_human_ids: JSON.stringify([humanId]),
            ratio: '16:9',
            resolution: '720p',
            image_model: 'gpt-image-2',
            video_model: 'doubao-seedance-2.0',
            ass_file: {
              name: '10012204-remote-e2e.ass',
              mimeType: 'text/plain',
              buffer: readFileSync(assFile),
            },
          },
        }),
      )
      expect(ass.status).toBe('parsed')
      expect(ass.lines.length).toBeGreaterThan(0)

      if (realGeneration) {
        // 两阶段流程：上传仅完成拆分，需先生成大纲再逐句生成
        // 大纲端点已异步化（202 受理 + 后台生成）：轮询任务状态直到离开 outlining（实测约 2 分钟）
        await json(await user.post(`/api/tasks/${ass.taskId}/storyboard-outline/regenerate`), 202)
        await expect
          .poll(
            async () => (await json(await user.get(`/api/tasks/${ass.taskId}`))).status as string,
            {
              timeout: 300_000,
              intervals: [2_000, 5_000],
            },
          )
          .not.toBe('outlining')
        const outlined = await json<{ status: string }>(await user.get(`/api/tasks/${ass.taskId}`))
        expect(outlined.status).toBe('generating')
        await json(
          await user.post(`/api/tasks/${ass.taskId}/storyboard-lines/${ass.lines[0].id}/generate`, {
            data: { force: false },
          }),
        )
        const imageJob = await json<{ id: string }>(
          await user.post('/api/generations/images', {
            data: { prompt: 'minimal remote API acceptance image', n: 1, purpose: 'other' },
          }),
          202,
        )
        await json(await user.get(`/api/generations/${imageJob.id}`))
      } else {
        // 大纲未生成时逐句生成被结构守卫拒绝
        expect(
          (
            await user.post(
              `/api/tasks/${ass.taskId}/storyboard-lines/${ass.lines[0].id}/generate`,
              { data: {} },
            )
          ).status(),
        ).toBe(422)
        expect(
          (
            await user.post(`/api/tasks/${ass.taskId}/storyboard-lines/missing-${runId}/generate`, {
              data: {},
            })
          ).status(),
        ).toBe(404)
        expect(
          (await user.post('/api/generations/images', { data: { prompt: '', n: 1 } })).status(),
        ).toBe(422)
        expect(
          (
            await user.post('/api/generations/videos', {
              data: { prompt: 'validation only', duration: 3 },
            })
          ).status(),
        ).toBe(422)
      }
      expect((await user.get(`/api/generations/missing-${runId}`)).status()).toBe(404)
      expect((await user.get(`/api/generations/missing-${runId}/events`)).status()).toBe(404)

      await json(await user.get(`/api/token-usage?project_task_id=${ass.taskId}`))
      const materialExport = await json<{ id: string }>(
        await user.post(`/api/tasks/${taskId}/material-exports`),
        202,
      )
      expect(materialExport.id).toBeTruthy()
      const exportStatus = await json<{ status: string }>(
        await user.get(`/api/material-exports/${materialExport.id}`),
      )
      expect(['queued', 'running', 'ready']).toContain(exportStatus.status)
      const exportHistory = await json<Record<string, unknown>[]>(
        await user.get(`/api/tasks/${taskId}/material-exports`),
      )
      expect(exportHistory.some((item) => item.id === materialExport.id)).toBeTruthy()
      const exportEvents = await user.get(`/api/material-exports/${materialExport.id}/events`, {
        timeout: 30_000,
      })
      expect(exportEvents.status()).toBe(200)
      const exportEventBody = await exportEvents.text()
      expect(exportEventBody).toContain('data: ')
      expect(exportEventBody).toContain('"type": "export"')
      expect(exportEventBody).toContain('"progress": 100')

      const chat = await json<{ id: string }>(
        await user.post('/api/chat/sessions', {
          data: { system_prompt: 'remote acceptance assistant' },
        }),
        201,
      )
      chatId = chat.id
      await json(await user.get('/api/chat/sessions'))
      await json(await user.get(`/api/chat/${chatId}`))
      if (realGeneration) {
        await json(
          await user.post(`/api/chat/${chatId}/messages`, { data: { text: 'reply with OK' } }),
          202,
        )
      } else {
        expect(
          (await user.post(`/api/chat/${chatId}/messages`, { data: { text: '' } })).status(),
        ).toBe(422)
      }
      await json(await user.post(`/api/chat/${chatId}/interrupt`))
      expect((await user.get(`/api/chat/missing-${runId}/events`)).status()).toBe(404)
      await json(await user.delete(`/api/chat/${chatId}`))
      chatId = ''

      await json(await user.delete(`/api/storyboard-lines/${line2.id}`))
      await json(await user.delete(`/api/tasks/${general.taskId}`))
      await json(await user.delete(`/api/tasks/${ass.taskId}`))
      await json(await user.delete(`/api/tasks/${taskId}`))
      await json(await user.delete(`/api/digital-humans/${humanId}`))
      humanId = ''
      await json(await user.delete(`/api/digital-human-styles/${styleId}`))
      styleId = ''
      await json(await user.delete(`/api/projects/${projectId}`))
      expect((await user.get(`/api/tasks/${taskId}`)).status()).toBe(404)
      projectId = ''
      await json(await user.post('/api/auth/logout'))
    } finally {
      await user.dispose()
    }

    const errorResponse = await admin.get(`/api/tasks/remote-e2e-missing-${runId}`)
    expect(errorResponse.status()).toBe(404)
    const errors = await json<{ items: { id: string; path: string }[] }>(
      await admin.get('/api/admin/api-errors?limit=100'),
    )
    const createdError = errors.items.find((item) =>
      item.path.includes(`remote-e2e-missing-${runId}`),
    )
    expect(createdError).toBeTruthy()
    await json(await admin.delete(`/api/admin/api-errors/${createdError.id}`))
  } finally {
    if (testUserId) {
      const deletion = await admin.delete(`/api/admin/users/${testUserId}`)
      expect([200, 404]).toContain(deletion.status())
    }
    await admin.post('/api/auth/logout')
    await admin.dispose()
    await publicApi.dispose()
  }
})
