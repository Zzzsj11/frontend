import type {
  DigitalHuman,
  GeneralStoryboardOptions,
  GeneralStoryboardRequest,
  GeneralStoryboardResult,
  MaterialExport,
  OutlineFailedSegment,
  OutlinePlannedLine,
  OutlineProgress,
  ScriptLine,
  ShotGenOptions,
  SongProject,
  StoryBible,
} from '../types'
import * as mediaGen from './mediaGen'
import { apiRequest, openApiStream } from './client'
import { DEFAULT_IMAGE_MODEL, DEFAULT_VIDEO_MODEL } from '../generationModels'

/**
 * 领域 API 门面 —— 镜像后端 domain 路由（backend/app/domain.py）：
 *  GET  /api/projects              -> fetchSongProjects
 *  GET  /api/tasks/{id}            -> fetchSongScript
 *  GET  /api/tasks/{id}/generations/active -> fetchActiveGenerations
 *  POST /api/projects              -> createSongProject
 *  GET  /api/digital-humans        -> fetchDigitalHumans
 *  POST /api/storyboards/ass       -> generateMagicScript
 *  POST /api/scene/generate        -> generateSceneImage（经 mediaGen 轮询任务）
 *  POST /api/shot/generate-video   -> generateShotVideo（经 mediaGen 轮询任务）
 *  配音接口见 ./voice.ts（占位实现，待后端接入）
 */

/** GET /api/songs — 歌曲项目列表（侧边栏目录，一个目录处理一首歌曲） */
export async function fetchSongProjects(): Promise<SongProject[]> {
  return apiRequest<SongProject[]>('/projects')
}

/** GET /api/songs/{id}/script — 载入某首歌曲的分镜脚本与角色阵容。
 *  固定 history=0 裁剪响应：每行只回传当前选用资产 + 历史版本计数，
 *  完整历史在打开分镜详情弹窗时经 fetchStoryboardLine 懒加载（P2 切换路径瘦身）。 */
export async function fetchSongScript(
  taskId: string,
  polling = false,
): Promise<{
  cast: string[]
  lines: ScriptLine[]
  storyboardType: string
  storyBible?: StoryBible
  status: string
  outlineProgress?: Record<string, unknown>
}> {
  const task = await apiRequest<{
    cast: string[]
    storyboardType: string
    status: string
    storyboardConfig?: { storyBible?: StoryBible; outlineProgress?: Record<string, unknown> }
    lines: Array<Record<string, unknown>>
  }>(`/tasks/${taskId}?history=0`, polling ? { headers: { 'X-Polling': '1' } } : {})
  return {
    cast: task.cast,
    storyboardType: task.storyboardType,
    status: task.status,
    storyBible: task.storyboardConfig?.storyBible,
    outlineProgress: task.storyboardConfig?.outlineProgress,
    lines: task.lines.map(mapScriptLine),
  }
}

/** 服务端单行 JSON → 前端 ScriptLine（history=0 时 shotAssets 仅含当前选用） */
function mapScriptLine(item: Record<string, unknown>): ScriptLine {
  const sceneAssets =
    (item.sceneAssets as Array<{
      id: string
      imageUrl: string
      originalImageUrl?: string
      isCurrent: boolean
    }>) || []
  const shotAssets =
    (item.shotAssets as Array<{
      id: string
      coverUrl: string
      originalCoverUrl?: string
      videoUrl: string
      duration: number
      isCurrent: boolean
    }>) || []
  const currentScene = sceneAssets.find((a) => a.isCurrent)
  const currentShot = shotAssets.find((a) => a.isCurrent)
  return {
    id: String(item.id),
    source: item.source as ScriptLine['source'],
    shotType: item.shotType as ScriptLine['shotType'],
    plannedDuration: item.plannedDuration as number | undefined,
    start: item.start as number | undefined,
    end: item.end as number | undefined,
    lyrics: String(item.lyrics || ''),
    lyricsZh: item.lyricsZh as string | undefined,
    scenePrompt: String(item.scenePrompt || ''),
    shotPrompt: String(item.shotPrompt || ''),
    digitalHumanIds: item.digitalHumanIds as string[],
    shotOptions: item.shotOptions as ScriptLine['shotOptions'],
    generationStatus: item.generationStatus as ScriptLine['generationStatus'],
    generationError: item.generationError as string | undefined,
    generationAttempt: Number(item.generationAttempt || 0),
    voice: { status: 'none' },
    scene: {
      status: sceneAssets.length ? 'done' : 'none',
      imageUrl: currentScene?.imageUrl,
      originalImageUrl: currentScene?.originalImageUrl,
    },
    shot: {
      status: shotAssets.length ? 'done' : 'none',
      imageUrl: currentShot?.coverUrl,
      assets: shotAssets.map((a) => ({
        ...a,
        digitalHumanIds: item.digitalHumanIds as string[],
      })),
      currentAssetId: currentShot?.id,
      // 响应裁剪时服务端回传历史版本总数；未裁剪（单行端点）时即实际长度
      assetCount: Number(item.shotAssetCount ?? shotAssets.length),
    },
  }
}

/** GET /api/tasks/{taskId}/storyboard-lines/{lineId} — 单行全量（含完整资产历史）：生成落定增量合并 / 详情弹窗懒加载历史版本 */
export async function fetchStoryboardLine(taskId: string, lineId: string): Promise<ScriptLine> {
  const item = await apiRequest<Record<string, unknown>>(
    `/tasks/${taskId}/storyboard-lines/${lineId}`,
    { headers: { 'X-Polling': '1' } },
  )
  return mapScriptLine(item)
}

/** GET /api/tasks/{id}/generations/active — 任务下仍在排队/执行中的媒体生成任务（刷新后恢复等待态） */
export const fetchActiveGenerations = (taskId: string) =>
  apiRequest<
    Array<{
      id: string
      kind: 'image' | 'video' | 'storyboard_line'
      storyboardLineId: string | null
    }>
  >(`/tasks/${taskId}/generations/active`)

/** 按任务 ID 恢复媒体生成任务的轮询等待（页面刷新后续跑；成功时资产已由后端落库） */
export const waitGenerationJob = (id: string, signal?: AbortSignal) =>
  mediaGen.waitForJob(id, 660_000, { signal })

export const acknowledgeGenerationResults = (ids: string[]) =>
  ids.length
    ? apiRequest<{ observed: number }>('/generations/observed', {
        method: 'POST',
        headers: { 'X-Polling': '1' },
        body: JSON.stringify({ ids }),
      })
    : Promise.resolve({ observed: 0 })

/** POST /api/songs — 新建空歌曲项目，用户随后选择 ASS 分镜或通用分镜 */
export async function createSongProject(name: string): Promise<SongProject> {
  return apiRequest<SongProject>('/projects', { method: 'POST', body: JSON.stringify({ name }) })
}

/** GET /api/assets/digital-humans — 数字人资产列表 */
export async function fetchDigitalHumans(): Promise<DigitalHuman[]> {
  return apiRequest<DigitalHuman[]>('/digital-humans')
}

/** ASS 上传响应：标题、阵容与时间轴拆分结果 */
export interface MagicScript {
  title: string
  cast: string[]
  /** 两阶段流程：上传仅完成时间轴拆分（parsed），大纲由独立端点生成 */
  status?: string
  lines: Array<{
    id?: string
    lyrics: string
    scenePrompt: string
    shotPrompt: string
    digitalHumanIds: string[]
    plannedDuration?: number
    shotOptions?: ShotGenOptions
    shotType?: 'empty' | 'character'
    generationStatus?: 'pending' | 'running' | 'succeeded' | 'failed'
    /** ASS 时间轴起止时间（秒） */
    start?: number
    end?: number
  }>
}

/** POST /api/script/magic 的请求参数（规划为 multipart/form-data） */
export interface MagicScriptRequest {
  projectId?: string
  /** 歌曲编号 */
  songId: string
  /** 歌词字幕 .ass 文件 */
  assFile: File
  /** 从已有数字人角色库选择的角色 id（可空/可多选） */
  digitalHumanIds?: string[]
  /** 额外要求（可空） */
  extraRequirement?: string
  ratio: ShotGenOptions['ratio']
  resolution: ShotGenOptions['resolution']
  imageModel: ShotGenOptions['imageModel']
  videoModel: ShotGenOptions['videoModel']
}

/** POST /api/script/magic — 根据歌曲编号 + ass 字幕 + 已选角色生成一套 MV 脚本 */
export async function generateMagicScript(
  req?: MagicScriptRequest,
): Promise<MagicScript & { taskId: string }> {
  if (!req) throw new Error('缺少 ASS 视频参数')
  if (!req.projectId) throw new Error('请先选择歌曲项目')
  const form = new FormData()
  form.append('song_id', req.songId)
  form.append('project_id', req.projectId)
  form.append('ass_file', req.assFile)
  form.append('digital_human_ids', JSON.stringify(req.digitalHumanIds ?? []))
  form.append('extra_requirement', req.extraRequirement ?? '')
  form.append('ratio', req.ratio)
  form.append('resolution', req.resolution)
  form.append('image_model', req.imageModel)
  form.append('video_model', req.videoModel)
  return apiRequest<MagicScript & { taskId: string }>('/storyboards/ass', {
    method: 'POST',
    body: form,
  })
}

export const updateSongProject = (id: string, name: string) =>
  apiRequest(`/projects/${id}`, { method: 'PATCH', body: JSON.stringify({ name }) })
export const deleteSongProject = (id: string) => apiRequest(`/projects/${id}`, { method: 'DELETE' })
export const reorderProjects = (order: string[]) =>
  apiRequest('/projects/reorder', { method: 'PATCH', body: JSON.stringify({ order }) })
export const reorderProjectTasks = (projectId: string, order: string[]) =>
  apiRequest(`/projects/${projectId}/tasks/reorder`, {
    method: 'PATCH',
    body: JSON.stringify({ order }),
  })
export const updateSongTask = (id: string, title: string) =>
  apiRequest(`/tasks/${id}`, { method: 'PATCH', body: JSON.stringify({ title }) })
export const deleteSongTask = (id: string) => apiRequest(`/tasks/${id}`, { method: 'DELETE' })
export const createDigitalHuman = (input: {
  name: string
  styleId?: string
  description: string
  avatar: string
  thumbnail?: string
  avatarPrompt?: string
  source: 'uploaded' | 'generated'
}) =>
  apiRequest<DigitalHuman>('/digital-humans', {
    method: 'POST',
    body: JSON.stringify({
      name: input.name,
      style_id: input.styleId,
      description: input.description,
      avatar_url: input.avatar,
      avatar_thumbnail_url: input.thumbnail,
      avatar_prompt: input.avatarPrompt || '',
      source: input.source,
    }),
  })
export const updateDigitalHuman = (id: string, input: Record<string, unknown>) =>
  apiRequest<DigitalHuman>(`/digital-humans/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(input),
  })
export const deleteDigitalHuman = (id: string) =>
  apiRequest(`/digital-humans/${id}`, { method: 'DELETE' })
export const fetchDigitalHumanStyles = () =>
  apiRequest<Array<{ id: string; name: string; scope: string; readOnly: boolean }>>(
    '/digital-human-styles',
  )
export const createDigitalHumanStyle = (name: string) =>
  apiRequest<{ id: string; name: string }>('/digital-human-styles', {
    method: 'POST',
    body: JSON.stringify({ name }),
  })
export const deleteDigitalHumanStyle = (id: string) =>
  apiRequest(`/digital-human-styles/${id}`, { method: 'DELETE' })

/**
 * Data URL 是页面内存中的图片，不应通过 fetch 读取：生产 CSP 的 connect-src
 * 不允许 data:，浏览器会在上传请求发出前抛出 `Failed to fetch`。
 */
export function dataUrlToBlob(dataUrl: string): Blob {
  const comma = dataUrl.indexOf(',')
  if (comma < 0 || !dataUrl.startsWith('data:')) throw new TypeError('无效的图片数据')
  const metadata = dataUrl.slice(5, comma)
  const encoded = dataUrl.slice(comma + 1)
  const base64 = metadata.endsWith(';base64')
  const mimeType = metadata.replace(/;base64$/, '') || 'application/octet-stream'
  const binary = base64 ? atob(encoded) : decodeURIComponent(encoded)
  const bytes = Uint8Array.from(binary, (char) => char.charCodeAt(0))
  return new Blob([bytes], { type: mimeType })
}

export async function uploadDataUrl(
  dataUrl: string,
  filename: string,
): Promise<{ url: string; thumbnailUrl?: string }> {
  const blob = dataUrlToBlob(dataUrl)
  const form = new FormData()
  form.append('file', blob, filename)
  return apiRequest<{ url: string; thumbnailUrl?: string }>('/uploads?category=digital-humans', {
    method: 'POST',
    body: form,
  })
}
export const exportMaterials = (taskId: string) =>
  apiRequest<MaterialExport>(`/tasks/${taskId}/material-exports`, { method: 'POST' })
export const fetchMaterialExports = (taskId: string) =>
  apiRequest<MaterialExport[]>(`/tasks/${taskId}/material-exports`)
export const fetchMaterialExport = (exportId: string) =>
  apiRequest<MaterialExport>(`/material-exports/${exportId}`)
/** GET /api/tasks/{id}/storyboard-outline/events — 大纲生成进度 SSE 流，终态（status 离开 outlining）后服务端关闭 */
export async function streamStoryboardOutline(
  taskId: string,
  onEvent: (event: { taskId: string; status: string; progress: OutlineProgress }) => void,
  signal?: AbortSignal,
): Promise<void> {
  const response = await openApiStream(
    `/tasks/${taskId}/storyboard-outline/events`,
    signal,
    true,
    // SSE 长连接：duration_ms 等于整个订阅时长，全量日志跳过
    { 'X-Polling': '1' },
  )
  if (!response.body) throw new Error('浏览器不支持实时进度流')
  const reader = response.body.getReader(),
    decoder = new TextDecoder()
  let buffer = ''
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const events = buffer.split('\n\n')
    buffer = events.pop() || ''
    for (const event of events) {
      const raw = event
        .split('\n')
        .find((line) => line.startsWith('data: '))
        ?.slice(6)
      if (!raw) continue
      const payload = JSON.parse(raw) as {
        type: string
        taskId: string
        status: string
        progress: OutlineProgress
      }
      if (payload.type === 'outline') onEvent(payload)
    }
  }
}

export async function streamMaterialExport(
  exportId: string,
  onExport: (item: MaterialExport) => void,
  signal?: AbortSignal,
): Promise<void> {
  const response = await openApiStream(
    `/material-exports/${exportId}/events`,
    signal,
    true,
    // SSE 长连接：duration_ms 等于整个订阅时长，全量日志跳过
    { 'X-Polling': '1' },
  )
  if (!response.body) throw new Error('浏览器不支持实时进度流')
  const reader = response.body.getReader(),
    decoder = new TextDecoder()
  let buffer = ''
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const events = buffer.split('\n\n')
    buffer = events.pop() || ''
    for (const event of events) {
      const raw = event
        .split('\n')
        .find((line) => line.startsWith('data: '))
        ?.slice(6)
      if (!raw) continue
      const payload = JSON.parse(raw) as { type: string; export: MaterialExport }
      if (payload.type === 'export') onExport(payload.export)
    }
  }
}
export const createStoryboardLine = (taskId: string, input: Record<string, unknown>) =>
  apiRequest<{ id: string }>(`/tasks/${taskId}/storyboard/lines`, {
    method: 'POST',
    body: JSON.stringify(input),
  })
export const updateStoryboardLine = (id: string, input: Record<string, unknown>) =>
  apiRequest(`/storyboard-lines/${id}`, { method: 'PATCH', body: JSON.stringify(input) })
export const deleteStoryboardLine = (id: string) =>
  apiRequest(`/storyboard-lines/${id}`, { method: 'DELETE' })
export const reorderStoryboardLines = (taskId: string, lineIds: string[]) =>
  apiRequest(`/tasks/${taskId}/storyboard/reorder`, {
    method: 'POST',
    body: JSON.stringify({ line_ids: lineIds }),
  })
export const updateTaskCast = (taskId: string, ids: string[]) =>
  apiRequest(`/tasks/${taskId}/cast`, {
    method: 'PUT',
    body: JSON.stringify({ digital_human_ids: ids }),
  })
export const generateStoryboardLine = (taskId: string, lineId: string, force = false) =>
  apiRequest<Record<string, unknown>>(`/tasks/${taskId}/storyboard-lines/${lineId}/generate`, {
    method: 'POST',
    body: JSON.stringify({ force }),
  })
export const resetFailedStoryboardLines = (taskId: string) =>
  apiRequest<{ lineIds: string[] }>(`/tasks/${taskId}/storyboard/retry-failed`, { method: 'POST' })
export const regenerateStoryboardOutline = (taskId: string) =>
  apiRequest<{
    taskId: string
    status: string
    progress: OutlineProgress
  }>(`/tasks/${taskId}/storyboard-outline/regenerate`, { method: 'POST' }, true, [409])
export const regenerateStoryboardOutlineSegment = (taskId: string, sceneIndex: number) =>
  apiRequest<{
    sceneIndex: number
    failedSegments: OutlineFailedSegment[]
    lines: OutlinePlannedLine[]
  }>(`/tasks/${taskId}/storyboard-outline/segments/${sceneIndex}/regenerate`, { method: 'POST' })

/** 通用分镜的可选项 —— 由后端组装（管理后台「通用分类」可配） */
export async function fetchGeneralStoryboardOptions(): Promise<GeneralStoryboardOptions> {
  return apiRequest<GeneralStoryboardOptions>('/storyboards/general/options')
}

export async function generateGeneralStoryboard(
  req: GeneralStoryboardRequest,
): Promise<GeneralStoryboardResult> {
  if (!req.projectId) throw new Error('请先选择歌曲项目')
  return apiRequest<GeneralStoryboardResult>(`/projects/${req.projectId}/storyboards/general`, {
    method: 'POST',
    body: JSON.stringify({
      genre: req.genre,
      secondary_category: req.secondaryCategory,
      tertiary_category: req.tertiaryCategory,
      season: req.season,
      gender: req.gender,
      age_group: req.ageGroup,
      visual_style: req.visualStyle,
      ratio: req.ratio,
      resolution: req.resolution,
      image_model: req.imageModel,
      video_model: req.videoModel,
      empty_shot_count: req.emptyShotCount,
      character_shot_count: req.characterShotCount,
      total_duration: req.totalDuration,
      digital_human_ids: req.digitalHumanIds ?? [],
      extra_requirement: req.extraRequirement ?? '',
      overall_prompt: req.extraRequirement ?? '',
    }),
  })
}

/** POST /api/scene/generate — 根据场景提示词生成分镜的背景场景图 */
export async function generateSceneImage(
  scenePrompt: string,
  _index: number,
  _variant: number,
  projectTaskId?: string,
  storyboardLineId?: string,
  ratio: ShotGenOptions['ratio'] = '16:9',
  imageModel?: ShotGenOptions['imageModel'],
  resolution: ShotGenOptions['resolution'] = '720p',
  signal?: AbortSignal,
): Promise<{ imageUrl: string; thumbnailUrl?: string }> {
  return mediaGen.generateScene(
    scenePrompt,
    projectTaskId,
    storyboardLineId,
    ratio,
    imageModel,
    resolution,
    signal,
  )
}

/** POST /api/shot/generate-video — 根据场景 + 分镜提示词 + 出演角色（可空/可多人）+ 生成参数（清晰度/时长/画幅）生成分镜视频片段 */
export async function generateShotVideo(
  scenePrompt: string,
  shotPrompt: string,
  characterImageUrls: string[],
  _index: number,
  _variant: number,
  options?: ShotGenOptions,
  referenceImageUrl?: string,
  projectTaskId?: string,
  storyboardLineId?: string,
  signal?: AbortSignal,
): Promise<{ coverUrl: string; coverThumbnailUrl?: string; videoUrl: string; duration: number }> {
  return mediaGen.generateShotVideo(
    [scenePrompt, shotPrompt].filter(Boolean).join('。'),
    referenceImageUrl,
    characterImageUrls,
    options ?? {
      resolution: '720p',
      duration: 5,
      ratio: '16:9',
      imageModel: DEFAULT_IMAGE_MODEL,
      videoModel: DEFAULT_VIDEO_MODEL,
      generateAudio: false,
      watermark: false,
    },
    projectTaskId,
    storyboardLineId,
    signal,
  )
}
