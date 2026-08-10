import type {
  DigitalHuman,
  GeneralStoryboardOptions,
  GeneralStoryboardRequest,
  GeneralStoryboardResult,
  MaterialExport,
  ScriptLine,
  ShotGenOptions,
  SongProject,
  StoryBible,
} from '../types'
import {
  makeSilentWav,
} from './data'
import type { MagicScript } from './data'
import * as mediaGen from '../api/mediaGen'
import { apiRequest, openApiStream } from '../api/client'
import { DEFAULT_IMAGE_MODEL, DEFAULT_VIDEO_MODEL } from '../generationModels'

/**
 * Mock API 层 —— 模拟后端接口，每个函数对应一个规划中的 HTTP 接口：
 *  GET  /api/songs                 -> fetchSongProjects
 *  GET  /api/songs/{id}/script     -> fetchSongScript
 *  POST /api/songs                 -> createSongProject
 *  GET  /api/assets/digital-humans -> fetchDigitalHumans
 *  POST /api/storyboards/ass       -> generateMagicScript (real backend)
 *  POST /api/voice/generate        -> generateVoice
 *  POST /api/scene/generate        -> generateSceneImage
 *  POST /api/shot/generate-video   -> generateShotVideo
 *  POST /api/video/synthesize      -> synthesizeVideo
 */

const delay = (min = 800, max = 2000) =>
  new Promise<void>((resolve) => setTimeout(resolve, min + Math.random() * (max - min)))

/** GET /api/songs — 歌曲项目列表（侧边栏目录，一个目录处理一首歌曲） */
export async function fetchSongProjects(): Promise<SongProject[]> {
  return apiRequest<SongProject[]>('/projects')
}

/** GET /api/songs/{id}/script — 载入某首歌曲的分镜脚本与角色阵容 */
export async function fetchSongScript(taskId: string): Promise<{ cast: string[]; lines: ScriptLine[]; storyboardType: string; storyBible?: StoryBible }> {
  const task = await apiRequest<{ cast: string[]; storyboardType:string; storyboardConfig?:{storyBible?:StoryBible}; lines: Array<Record<string, unknown>> }>(`/tasks/${taskId}`)
  return { cast: task.cast, storyboardType:task.storyboardType, storyBible:task.storyboardConfig?.storyBible, lines: task.lines.map((item) => {
    const sceneAssets = (item.sceneAssets as Array<{ id:string; imageUrl:string; originalImageUrl?:string; isCurrent:boolean }>) || []
    const shotAssets = (item.shotAssets as Array<{ id:string; coverUrl:string; originalCoverUrl?:string; videoUrl:string; duration:number; isCurrent:boolean }>) || []
    const currentScene = sceneAssets.find((a)=>a.isCurrent)
    const currentShot = shotAssets.find((a)=>a.isCurrent)
    return { id: String(item.id), source: item.source as ScriptLine['source'], shotType: item.shotType as ScriptLine['shotType'], plannedDuration: item.plannedDuration as number | undefined, lyrics: String(item.lyrics || ''), lyricsZh: item.lyricsZh as string | undefined, scenePrompt: String(item.scenePrompt || ''), shotPrompt: String(item.shotPrompt || ''), digitalHumanIds: item.digitalHumanIds as string[], shotOptions: item.shotOptions as ScriptLine['shotOptions'], generationStatus: item.generationStatus as ScriptLine['generationStatus'], generationError: item.generationError as string | undefined, generationAttempt: Number(item.generationAttempt || 0), voice: { status: 'none' }, scene: { status: sceneAssets.length ? 'done' : 'none', imageUrl: currentScene?.imageUrl, originalImageUrl: currentScene?.originalImageUrl }, shot: { status: shotAssets.length ? 'done' : 'none', imageUrl: currentShot?.coverUrl, assets: shotAssets.map((a)=>({ ...a, digitalHumanIds: item.digitalHumanIds as string[] })), currentAssetId: currentShot?.id } }
  }) }
}

/** POST /api/songs — 新建空歌曲项目，用户随后选择 ASS 分镜或通用分镜 */
export async function createSongProject(name: string): Promise<SongProject> {
  return apiRequest<SongProject>('/projects', { method: 'POST', body: JSON.stringify({ name }) })
}

/** GET /api/assets/digital-humans — 数字人资产列表 */
export async function fetchDigitalHumans(): Promise<DigitalHuman[]> {
  return apiRequest<DigitalHuman[]>('/digital-humans')
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
export async function generateMagicScript(req?: MagicScriptRequest): Promise<MagicScript & { taskId: string }> {
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
  return apiRequest<MagicScript & { taskId: string }>('/storyboards/ass', { method: 'POST', body: form })
}

export const updateSongProject = (id: string, name: string) => apiRequest(`/projects/${id}`, { method: 'PATCH', body: JSON.stringify({ name }) })
export const deleteSongProject = (id: string) => apiRequest(`/projects/${id}`, { method: 'DELETE' })
export const updateSongTask = (id: string, title: string) => apiRequest(`/tasks/${id}`, { method: 'PATCH', body: JSON.stringify({ title }) })
export const deleteSongTask = (id: string) => apiRequest(`/tasks/${id}`, { method: 'DELETE' })
export const createDigitalHuman = (input: { name:string; styleId?:string; description:string; avatar:string; thumbnail?:string; avatarPrompt?:string; source:'uploaded'|'generated' }) => apiRequest<DigitalHuman>('/digital-humans', { method:'POST', body:JSON.stringify({ name:input.name, style_id:input.styleId, description:input.description, avatar_url:input.avatar, avatar_thumbnail_url:input.thumbnail, avatar_prompt:input.avatarPrompt || '', source:input.source }) })
export const updateDigitalHuman = (id:string, input: Record<string, unknown>) => apiRequest<DigitalHuman>(`/digital-humans/${id}`, { method:'PATCH', body:JSON.stringify(input) })
export const deleteDigitalHuman = (id:string) => apiRequest(`/digital-humans/${id}`, { method:'DELETE' })
export const fetchDigitalHumanStyles = () => apiRequest<Array<{id:string;name:string;scope:string;readOnly:boolean}>>('/digital-human-styles')
export const createDigitalHumanStyle = (name:string) => apiRequest<{id:string;name:string}>('/digital-human-styles',{method:'POST',body:JSON.stringify({name})})
export const deleteDigitalHumanStyle = (id:string) => apiRequest(`/digital-human-styles/${id}`,{method:'DELETE'})
export async function uploadDataUrl(dataUrl:string, filename:string): Promise<{url:string;thumbnailUrl?:string}> { const response=await fetch(dataUrl); const blob=await response.blob(); const form=new FormData(); form.append('file',blob,filename); return apiRequest<{url:string;thumbnailUrl?:string}>('/uploads?category=digital-humans',{method:'POST',body:form}) }
export const exportMaterials = (taskId:string) => apiRequest<MaterialExport>(`/tasks/${taskId}/material-exports`,{method:'POST'})
export const fetchMaterialExports = (taskId:string) => apiRequest<MaterialExport[]>(`/tasks/${taskId}/material-exports`)
export const fetchMaterialExport = (exportId:string) => apiRequest<MaterialExport>(`/material-exports/${exportId}`)
export async function streamMaterialExport(exportId:string,onExport:(item:MaterialExport)=>void,signal?:AbortSignal):Promise<void>{
  const response=await openApiStream(`/material-exports/${exportId}/events`,signal)
  if(!response.body) throw new Error('浏览器不支持实时进度流')
  const reader=response.body.getReader(),decoder=new TextDecoder()
  let buffer=''
  for(;;){
    const {done,value}=await reader.read()
    if(done) break
    buffer+=decoder.decode(value,{stream:true})
    const events=buffer.split('\n\n');buffer=events.pop()||''
    for(const event of events){
      const raw=event.split('\n').find((line)=>line.startsWith('data: '))?.slice(6)
      if(!raw) continue
      const payload=JSON.parse(raw) as {type:string;export:MaterialExport}
      if(payload.type==='export') onExport(payload.export)
    }
  }
}
export const createStoryboardLine = (taskId:string,input:Record<string,unknown>) => apiRequest<{id:string}>(`/tasks/${taskId}/storyboard/lines`,{method:'POST',body:JSON.stringify(input)})
export const updateStoryboardLine = (id:string,input:Record<string,unknown>) => apiRequest(`/storyboard-lines/${id}`,{method:'PATCH',body:JSON.stringify(input)})
export const deleteStoryboardLine = (id:string) => apiRequest(`/storyboard-lines/${id}`,{method:'DELETE'})
export const reorderStoryboardLines = (taskId:string,lineIds:string[]) => apiRequest(`/tasks/${taskId}/storyboard/reorder`,{method:'POST',body:JSON.stringify({line_ids:lineIds})})
export const updateTaskCast = (taskId:string,ids:string[]) => apiRequest(`/tasks/${taskId}/cast`,{method:'PUT',body:JSON.stringify({digital_human_ids:ids})})
export const generateStoryboardLine = (taskId:string,lineId:string,force=false) => apiRequest<Record<string,unknown>>(`/tasks/${taskId}/storyboard-lines/${lineId}/generate`,{method:'POST',body:JSON.stringify({force})})
export const resetFailedStoryboardLines = (taskId:string) => apiRequest<{lineIds:string[]}>(`/tasks/${taskId}/storyboard/retry-failed`,{method:'POST'})
export const regenerateStoryboardOutline = (taskId:string) => apiRequest<{storyboardType:string;storyBible:StoryBible;lines:Array<{id:string;shotType:'empty'|'character';digitalHumanIds:string[];generationStatus:'pending'}>}>(`/tasks/${taskId}/storyboard-outline/regenerate`,{method:'POST'})

const generalStoryboardOptions: GeneralStoryboardOptions = {
  genres: [
    {
      value: 'pop', label: '流行', children: [
        { value: 'positive-love', label: '爱情积极', children: [
          { value: 'young-crush', label: '青涩心动' },
          { value: 'confession', label: '热烈告白' },
          { value: 'sweet-love', label: '甜蜜相恋' },
        ] },
        { value: 'negative-love', label: '爱情消极', children: [
          { value: 'regret', label: '遗憾错过' },
          { value: 'farewell', label: '失恋离别' },
          { value: 'lonely-memory', label: '孤独回忆' },
        ] },
        { value: 'inspiring', label: '励志', children: [
          { value: 'growth', label: '青春成长' },
          { value: 'dream', label: '追逐梦想' },
        ] },
      ],
    },
    {
      value: 'rock', label: '摇滚', children: [
        { value: 'passion', label: '热血', children: [
          { value: 'breakthrough', label: '突破束缚' },
          { value: 'live-stage', label: '现场舞台' },
        ] },
      ],
    },
    {
      value: 'folk', label: '民谣', children: [
        { value: 'narrative', label: '叙事', children: [
          { value: 'hometown', label: '故乡回忆' },
          { value: 'journey', label: '远方旅途' },
        ] },
      ],
    },
  ],
  seasons: ['春', '夏', '秋', '冬', '通用'],
  ageGroups: ['少儿', '青少年', '青年', '中年', '老年'],
  visualStyles: ['电影写实', '动漫', '国风', '复古', '赛博朋克'],
  ratios: ['16:9', '9:16', '4:3', '1:1'],
}

export async function fetchGeneralStoryboardOptions(): Promise<GeneralStoryboardOptions> {
  await delay(150, 350)
  return structuredClone(generalStoryboardOptions)
}

export async function generateGeneralStoryboard(req: GeneralStoryboardRequest): Promise<GeneralStoryboardResult> {
  if (!req.projectId) throw new Error('请先选择歌曲项目')
  return apiRequest<GeneralStoryboardResult>(`/projects/${req.projectId}/storyboards/general`, { method: 'POST', body: JSON.stringify({ genre: req.genre, secondary_category: req.secondaryCategory, tertiary_category: req.tertiaryCategory, season: req.season, singer: req.singer, age_group: req.ageGroup, visual_style: req.visualStyle, ratio: req.ratio, resolution: req.resolution, image_model: req.imageModel, video_model: req.videoModel, empty_shot_count: req.emptyShotCount, character_shot_count: req.characterShotCount, total_duration: req.totalDuration, digital_human_ids: req.digitalHumanIds ?? [], extra_requirement: req.extraRequirement ?? '', overall_prompt: req.extraRequirement ?? '' }) })
}

/** POST /api/voice/generate — 返回当前分镜的演唱/配音音频与时长 */
export async function generateVoice(_lineId: string): Promise<{ url: string; duration: number }> {
  await delay()
  const duration = Math.round((2 + Math.random() * 4) * 10) / 10 // 2~6s
  return { url: makeSilentWav(duration), duration }
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
): Promise<{ imageUrl: string; thumbnailUrl?: string }> {
  return mediaGen.generateScene(scenePrompt, projectTaskId, storyboardLineId, ratio, imageModel, resolution)
}

/** POST /api/shot/generate-video — 根据场景 + 分镜提示词 + 出演角色（可空/可多人）+ 生成参数（清晰度/时长/画幅）生成分镜视频片段 */
export async function generateShotVideo(
  scenePrompt: string,
  shotPrompt: string,
  _digitalHumanIds: string[],
  _index: number,
  _variant: number,
  options?: ShotGenOptions,
  referenceImageUrl?: string,
  projectTaskId?: string,
  storyboardLineId?: string,
): Promise<{ coverUrl: string; coverThumbnailUrl?: string; videoUrl: string; duration: number }> {
  return mediaGen.generateShotVideo(
    [scenePrompt, shotPrompt].filter(Boolean).join('。'),
    referenceImageUrl,
    options ?? { resolution: '720p', duration: 5, ratio: '16:9', imageModel: DEFAULT_IMAGE_MODEL, videoModel: DEFAULT_VIDEO_MODEL },
    projectTaskId,
    storyboardLineId,
  )
}

/** POST /api/video/synthesize — 模拟合成进度，最后返回假视频地址 */
export async function synthesizeVideo(onProgress: (p: number) => void): Promise<{ videoUrl: string }> {
  for (let p = 0; p <= 100; p += 5 + Math.floor(Math.random() * 10)) {
    onProgress(Math.min(p, 100))
    await delay(150, 350)
  }
  onProgress(100)
  return { videoUrl: 'mock://video/final.mp4' }
}
