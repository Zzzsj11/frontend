import { randomUUID } from 'node:crypto'
import { expect, test, type Locator, type Page, type Request } from '@playwright/test'
import type { DigitalHuman } from '../../src/types'

// 即使外部配置指向远程环境，本文件也只加载本机页面；所有 API 和网络图片均在浏览器侧截断。
const ORIGIN = 'http://127.0.0.1:4173'
const MEDIA = 'https://headshot.tos.test'
const REFERENCE = `${MEDIA}/user-reference-original.svg`
const PROMPT = '单人正面大头照，身份特征由服务端模板编译'
const STYLE = '自定义'
const svg = (width = 1024, height = 1536) =>
  `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}"><rect width="100%" height="100%" fill="#dddddd"/><ellipse cx="${width / 2}" cy="${height / 3}" rx="${width / 5}" ry="${height / 5}" fill="#996655"/></svg>`
const referenceFile = {
  name: 'reference.svg',
  mimeType: 'image/svg+xml',
  buffer: Buffer.from(svg()),
}

function human(id: string, name: string, system = false): DigitalHuman {
  return {
    id,
    name,
    style: system ? '男' : STYLE,
    description: '短发、青年、圆脸',
    avatar: `${MEDIA}/${id}-thumbnail.svg`,
    originalAvatar: `${MEDIA}/${id}-original.svg`,
    scope: system ? 'system' : 'private',
    readOnly: system,
  }
}

type Body = Record<string, unknown>
type Job = {
  id: string
  status: 'running' | 'succeeded' | 'failed'
  progress: number
  result: { urls: string[]; thumbnailUrls: string[] }
  error?: string
}
const safety = new WeakMap<Page, { unexpected: string[]; pageErrors: string[] }>()
test.use({ baseURL: ORIGIN, serviceWorkers: 'block' })

test.afterEach(async ({ page }) => {
  const recorded = safety.get(page)
  expect(recorded?.unexpected ?? [], '未声明的网络请求必须失败，不能穿透真实服务').toEqual([])
  expect(recorded?.pageErrors ?? [], '页面不应产生未处理异常').toEqual([])
})

async function mockApp(page: Page) {
  const runId = `headshot-${randomUUID()}`
  const state = {
    runId,
    authenticated: false,
    humans: [
      { ...human('system-legacy', '系统旧头像', true), assetCode: '001' },
      human('system-headshot', '系统大头照', true),
      human('private-legacy', '私有旧头像'),
      human('private-headshot', '私有大头照'),
    ],
    uploads: [] as Request[],
    generations: [] as Body[],
    creates: [] as Body[],
    patches: [] as { id: string; body: Body }[],
    polls: [] as string[][],
    apiCalls: [] as string[],
    jobs: [] as Job[],
    generationStatus: 'succeeded' as Job['status'],
    createGate: null as Promise<void> | null,
    patchGate: null as Promise<void> | null,
    failAvatarPatch: false,
    unexpected: [] as string[],
    pageErrors: [] as string[],
  }
  safety.set(page, state)
  page.on('pageerror', (error) => state.pageErrors.push(error.message))
  const user = {
    id: 'user-headshot',
    username: 'headshot-user',
    displayName: '大头照测试用户',
    role: 'user',
    isSuperAdmin: false,
    permissions: [],
    mustChangePassword: false,
  }
  const auth = { accessToken: 'mock-headshot-token', user }
  const getResponses: Record<string, unknown> = {
    '/api/release': { version: 'test' },
    '/api/auth/me': user,
    '/api/projects': [{ id: 'project-headshot', name: '大头照旅程', tasks: [] }],
    '/api/digital-human-styles': [
      { id: 'style-system', name: '男', scope: 'system', readOnly: true },
      { id: 'style-private', name: STYLE, scope: 'private', readOnly: false },
    ],
    '/api/account/balance': {
      available: true,
      balance: '287.391936',
      balanceDisplay: '287.39',
      currency: 'credits',
      updatedAt: '2026-09-21T00:00:00Z',
    },
    '/api/model-options': [
      { id: 'gpt-image-2.5-sunburst', name: '精细', modality: 'image', sortOrder: 10 },
      { id: 'gpt-image-2.5-flare', name: '快速', modality: 'image', sortOrder: 20 },
      { id: 'gpt-image-2', name: 'Img2', modality: 'image', sortOrder: 100 },
      { id: 'doubao-seedance-2.0', name: 'SD2.0', modality: 'video' },
    ],
    '/api/storyboards/general/options': {
      genres: [{ value: '流行歌曲', label: '流行歌曲' }],
      seasons: ['春', '夏', '秋', '冬', '通用'],
      ageGroups: ['青年'],
      visualStyles: ['电影写实'],
      ratios: ['16:9', '9:16', '4:3', '1:1'],
    },
    '/api/creative/status': {
      providers: {
        gemini: { configured: false, model: 'mock' },
        minimax: { configured: false, model: 'mock' },
      },
      limits: { images: 9, videos: 3, audios: 3, videoSeconds: 15, audioSeconds: 15 },
      ratios: ['16:9', '9:16'],
      durationRange: [4, 15],
    },
  }

  // 仅静态页面/模块可直通本机 Vite。API 分支绝不 continue/fallback，包括未知端点。
  await page.context().route('**/*', async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    const path = url.pathname
    const method = request.method()
    const json = (body: unknown, status = 200) =>
      route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
    if (path.startsWith('/api/')) {
      state.apiCalls.push(`${method} ${path}`)
      const headers = request.headers()
      // 不注入测试头：验证登录链接触发的真实前端归因逻辑，刷新后也须保留三头。
      expect(headers['x-agent-name'], path).toBe('code-agent')
      expect(headers['x-agent-run-id'], path).toBe(runId)
      expect(headers['x-test-run-id'], path).toBe(runId)
      if (method === 'POST' && path === '/api/auth/login') {
        state.authenticated = true
        return json(auth)
      }
      if (method === 'POST' && path === '/api/auth/refresh')
        return state.authenticated ? json(auth) : json({}, 401)
      if (method === 'GET' && path === '/api/digital-humans') return json(state.humans)
      if (method === 'GET' && path in getResponses) return json(getResponses[path])
      if (method === 'POST' && path === '/api/uploads') {
        expect(url.searchParams.get('category')).toBe('digital-humans')
        expect(headers['content-type']).toContain('multipart/form-data; boundary=')
        state.uploads.push(request)
        return json({ url: REFERENCE, thumbnailUrl: `${MEDIA}/user-reference-thumbnail.svg` })
      }
      if (method === 'POST' && path === '/api/generations/images') {
        state.generations.push(request.postDataJSON() as Body)
        const id = `job-${state.generations.length}`
        state.jobs.push({
          id,
          status: state.generationStatus,
          progress: state.generationStatus === 'running' ? 40 : 100,
          result: {
            urls: [`${MEDIA}/${id}-original.svg`],
            thumbnailUrls: [`${MEDIA}/${id}-thumbnail.svg`],
          },
          ...(state.generationStatus === 'failed' ? { error: '模拟生成失败，请重试' } : {}),
        })
        return json({ id, status: 'queued', progress: 0, prompt: PROMPT }, 202)
      }
      if (method === 'POST' && path === '/api/generations/status') {
        const { ids } = request.postDataJSON() as { ids: string[] }
        state.polls.push(ids)
        expect(headers['x-polling']).toBe('1')
        expect(ids.every((id) => state.jobs.some((job) => job.id === id))).toBe(true)
        return json(state.jobs.filter((job) => ids.includes(job.id)))
      }
      if (method === 'POST' && path === '/api/generations/observed') return json({ ok: true })
      if (method === 'POST' && path === '/api/generations/images/portrait-prompt')
        return json({ prompt: PROMPT })
      if (method === 'POST' && path === '/api/digital-humans') {
        const body = request.postDataJSON() as Body
        state.creates.push(body)
        if (state.createGate) await state.createGate
        const created = {
          ...human(`created-${state.creates.length}`, String(body.name)),
          description: String(body.description),
          avatar: String(body.avatar_thumbnail_url || body.avatar_url),
          originalAvatar: String(body.avatar_url),
          avatarPrompt: String(body.avatar_prompt),
        }
        state.humans.push(created)
        return json(created, 201)
      }
      if (method === 'PATCH' && path.startsWith('/api/digital-humans/')) {
        const id = path.split('/').at(-1)!
        const body = request.postDataJSON() as Body
        state.patches.push({ id, body })
        const current = state.humans.find((item) => item.id === id)
        expect(current, '只能更新已有私人人物').toBeDefined()
        expect(current?.readOnly, '系统人物不能发出修改请求').toBe(false)
        if (body.avatar_url) {
          if (state.patchGate) await state.patchGate
          if (state.failAvatarPatch) return json({ detail: '模拟头像保存失败，请重试' }, 500)
          Object.assign(current!, {
            avatar: body.avatar_thumbnail_url || body.avatar_url,
            originalAvatar: body.avatar_url,
            avatarPrompt: body.avatar_prompt,
          })
        } else {
          if (typeof body.name === 'string') current!.name = body.name
          if (typeof body.description === 'string') current!.description = body.description
        }
        return json(current)
      }
      state.unexpected.push(`${method} ${request.url()}`)
      return json({ detail: '未声明的 mock API；已阻止真实请求' }, 501)
    }
    if (request.resourceType() === 'image' || url.origin === MEDIA) {
      // 系统旧头像恰好 1.5，私有旧头像为 3，覆盖阈值及新竖图的混合列表。
      const dimensions = path.includes('system-legacy')
        ? [1536, 1024]
        : path.includes('private-legacy')
          ? [3072, 1024]
          : [1024, 1536]
      return route.fulfill({
        contentType: 'image/svg+xml',
        headers: { 'Access-Control-Allow-Origin': '*' },
        body: svg(dimensions[0], dimensions[1]),
      })
    }
    if (url.origin === ORIGIN && method === 'GET') return route.continue()
    state.unexpected.push(`${method} ${request.url()}`)
    return route.abort('blockedbyclient')
  })
  return state
}

async function login(page: Page, runId: string) {
  const destination = `/projects?agent_test_run_id=${runId}`
  await page.goto(`/login?agent_test_run_id=${runId}&redirect=${encodeURIComponent(destination)}`)
  await page.getByLabel('用户名').fill('headshot-user')
  await page.getByLabel('密码').fill('mock-only-password')
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await expect(page.getByRole('heading', { name: '视频编辑器' })).toBeVisible()
  await expect(page.getByRole('alertdialog')).toHaveCount(0)
}

async function openLibrary(page: Page) {
  await page.getByRole('button', { name: /^角色阵容/ }).click()
  const library = page.getByRole('dialog', { name: '数字人资产库', exact: true })
  await expect(library.locator('.dh-card')).toHaveCount(4)
  return library
}

async function fillUpload(library: Locator, name: string, description: string, withImage = true) {
  await library.getByRole('button', { name: '上传数字人', exact: true }).click()
  await library.getByPlaceholder('人物名称（必填）').fill(name)
  await library.getByPlaceholder('风格分类（必填）').fill(STYLE)
  await library.getByPlaceholder(/身份特征（可选/).fill(description)
  if (withImage) {
    await library.locator('input[type="file"][accept="image/*"]').setInputFiles(referenceFile)
    await expect(library.getByAltText('头像预览')).toBeVisible()
  }
  await expect(library.getByRole('button', { name: '添加到资产库' })).toBeEnabled()
}

function expectGeneration(body: Body, description: string, reference?: string) {
  expect(body).toMatchObject({
    prompt: '',
    size: '1024x1536',
    quality: 'medium',
    n: 1,
    purpose: 'digital_human',
    portrait: { description, style: STYLE },
  })
  if (reference) expect(body.images).toEqual([reference])
  else expect(body).not.toHaveProperty('images')
}

const cardNamed = (library: Locator, name: string) =>
  library.locator('.dh-card').filter({ has: library.page().getByText(name, { exact: true }) })

async function expectPortrait(card: Locator, src: string, legacy: boolean) {
  const image = card.locator('img').first()
  await expect(image).toHaveAttribute('src', src)
  await expect
    .poll(() =>
      image.evaluate(
        (img: HTMLImageElement) =>
          img.complete && img.naturalWidth > 0 && img.currentSrc === img.src,
      ),
    )
    .toBe(true)
  const ratio = await image.evaluate(
    (img: HTMLImageElement) => img.naturalWidth / img.naturalHeight,
  )
  expect(ratio >= 1.5).toBe(legacy)
  const portrait = card.locator('.character-portrait')
  const frame = await card.locator('.dh-portrait').boundingBox()
  expect(frame).not.toBeNull()
  expect(frame!.width / frame!.height).toBeCloseTo(2 / 3, 2)
  if (legacy) await expect(portrait).toHaveClass(/\blegacy-sheet\b/)
  else await expect(portrait).not.toHaveClass(/\blegacy-sheet\b/)
}

async function confirmRegeneration(page: Page, editor: Locator) {
  await editor.getByRole('button', { name: /重新生成形象|重新生成大头照/ }).click()
  await page
    .getByRole('alertdialog', { name: /重新生成数字人/ })
    .getByRole('button', { name: '重新生成', exact: true })
    .click()
}

test('损坏的参考图提示重新选择，保留表单且不提交生成', async ({ page }) => {
  const mock = await mockApp(page)
  await login(page, mock.runId)
  const library = await openLibrary(page)
  await fillUpload(library, '重新选图人物', '黑发青年', false)
  await library.locator('input[type="file"][accept="image/*"]').setInputFiles({
    name: 'broken.png',
    mimeType: 'image/png',
    buffer: Buffer.from('not an image'),
  })
  await expect(library.getByRole('alert')).toHaveText('图片无法读取，请重新选择')
  await expect(library.getByPlaceholder('人物名称（必填）')).toHaveValue('重新选图人物')
  expect(mock.generations).toHaveLength(0)
  expect(mock.uploads).toHaveLength(0)
  await library.locator('input[type="file"][accept="image/*"]').setInputFiles(referenceFile)
  await expect(library.getByAltText('头像预览')).toBeVisible()
  await expect(library.getByRole('alert')).toHaveCount(0)
  await library.getByRole('button', { name: '添加到资产库' }).click()
  await expect(cardNamed(library, '重新选图人物')).toBeVisible()
  expectGeneration(mock.generations[0]!, '黑发青年', REFERENCE)
})

test('上传参考原图生成竖版大头照，入库成功后展示，阵容仍须手动选择', async ({ page }) => {
  const mock = await mockApp(page)
  let allowCreate!: () => void
  mock.createGate = new Promise<void>((resolve) => {
    allowCreate = resolve
  })
  await login(page, mock.runId)
  const library = await openLibrary(page)
  await fillUpload(library, '上传新人物', '黑发、圆脸、青年')
  await expect(library).not.toContainText(/三视图|多视图/)
  await expect(library.locator('.upload-tip')).toContainText('大头照')
  await library.getByRole('button', { name: '添加到资产库' }).click()
  try {
    await expect.poll(() => mock.creates.length).toBe(1)
    expect(mock.uploads).toHaveLength(1)
    expect(mock.generations).toHaveLength(1)
    expectGeneration(mock.generations[0]!, '黑发、圆脸、青年', REFERENCE)
    const job = mock.jobs[0]!
    expect(mock.creates[0]).toMatchObject({
      name: '上传新人物',
      style_id: 'style-private',
      description: '黑发、圆脸、青年',
      avatar_url: job.result.urls[0],
      avatar_thumbnail_url: job.result.thumbnailUrls[0],
      avatar_prompt: PROMPT,
      source: 'uploaded',
    })
    expect(mock.apiCalls.indexOf('POST /api/uploads')).toBeLessThan(
      mock.apiCalls.indexOf('POST /api/generations/images'),
    )
    expect(mock.apiCalls.indexOf('POST /api/generations/status')).toBeLessThan(
      mock.apiCalls.indexOf('POST /api/digital-humans'),
    )
    await expect(cardNamed(library, '上传新人物')).toHaveCount(0)
    await expect(library.locator('.cast-label')).toHaveText('当前阵容（0）：')
  } finally {
    allowCreate()
  }
  const created = cardNamed(library, '上传新人物')
  await expect(created).toBeVisible()
  await expectPortrait(created, mock.jobs[0]!.result.thumbnailUrls[0]!, false)
  await expect(library.locator('.upload-panel')).toBeHidden()
  await expect(library.locator('.cast-label')).toHaveText('当前阵容（0）：')
  await expect(created).not.toHaveClass(/\bactive\b/)
  await created.hover()
  await created.getByRole('button', { name: '大图', exact: true }).click()
  await expect(page.locator('.preview-dialog img')).toHaveAttribute(
    'src',
    mock.jobs[0]!.result.urls[0]!,
  )
  await page.locator('.preview-close').click()
  await created.hover()
  await created.getByRole('button', { name: '加入阵容', exact: true }).click()
  await expect(library.locator('.cast-label')).toHaveText('当前阵容（1）：')
  await expect(library.locator('.cast-chip')).toContainText('上传新人物')
  await expect(created).toHaveClass(/\bactive\b/)
  await expect(page.getByRole('alertdialog')).toHaveCount(0)
})

test('新旧系统和私有头像混合展示；私有重生只用当前原图，PATCH 成功前不换图', async ({ page }) => {
  const mock = await mockApp(page)
  await login(page, mock.runId)
  const library = await openLibrary(page)
  for (const item of mock.humans) {
    await expectPortrait(cardNamed(library, item.name), item.avatar, item.id.includes('legacy'))
  }
  await page.screenshot({ path: test.info().outputPath('mixed-headshot-library.png') })
  for (const system of mock.humans.filter((item) => item.readOnly)) {
    const card = cardNamed(library, system.name)
    await card.hover()
    await card.getByRole('button', { name: '详情', exact: true }).click()
    const editor = page.getByRole('dialog', { name: `编辑数字人 · ${system.name}`, exact: true })
    await expect(editor.locator('.edit-portrait > img')).toHaveAttribute(
      'src',
      system.originalAvatar!,
    )
    await expect(editor.locator('.edit-form input')).toHaveCount(2)
    for (const input of await editor.locator('.edit-form input, .edit-form textarea').all())
      await expect(input).toBeDisabled()
    await expect(editor.getByRole('button', { name: /重新生成|删除数字人|保存/ })).toHaveCount(0)
    await editor.locator('.modal-header').getByRole('button', { name: '关闭' }).click()
  }
  expect(mock.generations).toHaveLength(0)
  expect(mock.patches).toHaveLength(0)

  const legacy = mock.humans.find((item) => item.id === 'private-legacy')!
  const oldAvatar = legacy.avatar
  const oldOriginal = legacy.originalAvatar!
  const card = cardNamed(library, legacy.name)
  await card.hover()
  await card.getByRole('button', { name: '详情', exact: true }).click()
  const editor = page.getByRole('dialog', { name: `编辑数字人 · ${legacy.name}`, exact: true })
  await expect(editor).not.toContainText(/三视图|多视图/)
  await editor.locator('.edit-form textarea').fill('棕发、青年、圆脸')
  let allowPatch!: () => void
  mock.patchGate = new Promise<void>((resolve) => {
    allowPatch = resolve
  })
  await confirmRegeneration(page, editor)
  try {
    await expect.poll(() => mock.patches.filter((patch) => patch.body.avatar_url).length).toBe(1)
    expectGeneration(mock.generations[0]!, '棕发、青年、圆脸', oldOriginal)
    expect(mock.patches.find((patch) => patch.body.avatar_url)).toMatchObject({
      id: legacy.id,
      body: {
        avatar_url: mock.jobs[0]!.result.urls[0],
        avatar_thumbnail_url: mock.jobs[0]!.result.thumbnailUrls[0],
      },
    })
    await expectPortrait(card, oldAvatar, true)
    await expect(editor.locator('.edit-portrait > img')).toHaveAttribute('src', oldOriginal)
    await expect(editor.locator('.edit-regen')).toBeDisabled()
  } finally {
    allowPatch()
  }
  const saved = mock.jobs[0]!.result
  await expectPortrait(card, saved.thumbnailUrls[0]!, false)
  await expect(editor.locator('.edit-portrait > img')).toHaveAttribute('src', saved.urls[0]!)
  await expect(editor.locator('.edit-regen')).toBeEnabled()

  // 第二次重生必须引用已保存的新原图；保存失败不能把生成结果提前写进列表或详情。
  mock.patchGate = null
  mock.failAvatarPatch = true
  await confirmRegeneration(page, editor)
  await expect(editor.locator('.gen-error')).toHaveText('模拟头像保存失败，请重试')
  expectGeneration(mock.generations[1]!, '棕发、青年、圆脸', saved.urls[0])
  await expectPortrait(card, saved.thumbnailUrls[0]!, false)
  await expect(editor.locator('.edit-portrait > img')).toHaveAttribute('src', saved.urls[0]!)
  await expect(editor.locator('.edit-form textarea')).toHaveValue('棕发、青年、圆脸')
  const error = page.getByRole('alertdialog')
  await expect(error).toContainText('模拟头像保存失败')
  await error.getByRole('button', { name: '我知道了' }).click()
  mock.failAvatarPatch = false
  await confirmRegeneration(page, editor)
  await expect.poll(() => mock.generations.length).toBe(3)
  expectGeneration(mock.generations[2]!, '棕发、青年、圆脸', saved.urls[0])
  await expectPortrait(card, mock.jobs[2]!.result.thumbnailUrls[0]!, false)
  await expect(editor.locator('.edit-portrait > img')).toHaveAttribute(
    'src',
    mock.jobs[2]!.result.urls[0]!,
  )
  expect(mock.uploads).toHaveLength(0)
  expect(mock.creates).toHaveLength(0)
  expect(mock.patches.every((patch) => patch.id === legacy.id)).toBe(true)
  await expect(page.getByRole('alertdialog')).toHaveCount(0)
})

test('无参考图时省略 images；生成等待中刷新从 mv:pending-dh 续等并只入库一次', async ({ page }) => {
  const mock = await mockApp(page)
  mock.generationStatus = 'running'
  await login(page, mock.runId)
  const library = await openLibrary(page)
  await fillUpload(library, '刷新续等人物', '', false)
  await library.getByRole('button', { name: '添加到资产库' }).click()
  await expect.poll(() => mock.polls.length).toBeGreaterThan(0)
  expect(mock.generations).toHaveLength(1)
  expectGeneration(mock.generations[0]!, '')
  expect(mock.uploads).toHaveLength(0)
  expect(mock.creates).toHaveLength(0)
  // 不预置 localStorage：必须由刚才的 UI 提交落下真实待恢复草稿。
  const draft = await page.evaluate(() =>
    JSON.parse(localStorage.getItem('mv:pending-dh') || 'null'),
  )
  expect(draft).toMatchObject({
    jobId: mock.jobs[0]!.id,
    name: '刷新续等人物',
    style: STYLE,
    description: '',
  })
  await expect(library.locator('.gen-submit')).toBeDisabled()
  await expect(library.locator('.gen-submit')).toContainText('大头照')
  const pollsBeforeReload = mock.polls.length
  expect(new URL(page.url()).searchParams.get('agent_test_run_id')).toBe(mock.runId)
  await page.reload()
  await expect(page.getByRole('heading', { name: '视频编辑器' })).toBeVisible()
  await expect.poll(() => mock.polls.length).toBeGreaterThan(pollsBeforeReload)
  const restored = await openLibrary(page)
  await restored.getByRole('button', { name: '上传数字人', exact: true }).click()
  await expect(restored.locator('.gen-submit')).toBeDisabled()
  await expect(restored.locator('.gen-submit')).toContainText('大头照')
  expect(mock.generations).toHaveLength(1)
  expect(mock.creates).toHaveLength(0)
  expect(mock.polls.every((ids) => ids.length === 1 && ids[0] === draft.jobId)).toBe(true)
  mock.jobs[0]!.status = 'succeeded'
  const card = cardNamed(restored, '刷新续等人物')
  await expect(card).toBeVisible({ timeout: 10_000 })
  await expectPortrait(card, mock.jobs[0]!.result.thumbnailUrls[0]!, false)
  await expect(restored.locator('.cast-label')).toHaveText('当前阵容（0）：')
  await expect.poll(() => page.evaluate(() => localStorage.getItem('mv:pending-dh'))).toBeNull()
  expect(mock.creates).toHaveLength(1)
  await page.reload()
  await expect(page.getByRole('heading', { name: '视频编辑器' })).toBeVisible()
  await page.getByRole('button', { name: /^角色阵容/ }).click()
  await expect(
    cardNamed(page.getByRole('dialog', { name: '数字人资产库', exact: true }), '刷新续等人物'),
  ).toHaveCount(1)
  expect(mock.generations).toHaveLength(1)
  expect(mock.creates).toHaveLength(1)
  expect(mock.uploads).toHaveLength(0)
  await expect(page.getByRole('alertdialog')).toHaveCount(0)
})

test('生成失败保留名称、分类、身份特征和参考预览，可原表单重试', async ({ page }) => {
  const mock = await mockApp(page)
  mock.generationStatus = 'failed'
  await login(page, mock.runId)
  const library = await openLibrary(page)
  await fillUpload(library, '失败重试人物', '银发、椭圆脸')
  const preview = await library.getByAltText('头像预览').getAttribute('src')
  await library.getByRole('button', { name: '添加到资产库' }).click()
  await expect(library.getByRole('alert')).toHaveText('模拟生成失败，请重试')
  await expect(library.getByPlaceholder('人物名称（必填）')).toHaveValue('失败重试人物')
  await expect(library.getByPlaceholder('风格分类（必填）')).toHaveValue(STYLE)
  await expect(library.getByPlaceholder(/身份特征（可选/)).toHaveValue('银发、椭圆脸')
  await expect(library.getByAltText('头像预览')).toHaveAttribute('src', preview!)
  await expect(library.getByRole('button', { name: '添加到资产库' })).toBeEnabled()
  await expect(cardNamed(library, '失败重试人物')).toHaveCount(0)
  await expect(library.locator('.cast-label')).toHaveText('当前阵容（0）：')
  await expect.poll(() => page.evaluate(() => localStorage.getItem('mv:pending-dh'))).toBeNull()
  expect(mock.creates).toHaveLength(0)
  expect(mock.generations).toHaveLength(1)
  expectGeneration(mock.generations[0]!, '银发、椭圆脸', REFERENCE)
  mock.generationStatus = 'succeeded'
  await library.getByRole('button', { name: '添加到资产库' }).click()
  const card = cardNamed(library, '失败重试人物')
  await expect(card).toBeVisible()
  await expectPortrait(card, mock.jobs[1]!.result.thumbnailUrls[0]!, false)
  expect(mock.generations).toHaveLength(2)
  expectGeneration(mock.generations[1]!, '银发、椭圆脸', REFERENCE)
  expect(mock.creates).toHaveLength(1)
  await expect(library.locator('.cast-label')).toHaveText('当前阵容（0）：')
  await expect(page.getByRole('alertdialog')).toHaveCount(0)
})
