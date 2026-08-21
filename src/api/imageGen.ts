/** 图片生成由 Python 后端代理，第三方密钥不会再暴露到浏览器。 */

import { apiRequest } from './client'
import { watchGenerationJob, type GenerationJobSnapshot } from '../utils/generationPoller'

export interface ImageTaskOptions {
  /** WIDTHxHEIGHT，宽 × 高必须小于 8,294,400，默认 1024x1024 */
  size?: string
  quality?: 'auto' | 'low' | 'medium' | 'high'
  /** 生成图片数量 1-4 */
  n?: number
  /** 图片 URL（或数组）：传入即按图生图处理，不传为文生图 */
  image?: string | string[]
  /** 数字人定妆照模式：prompt 由后端按注册中心模板拼装，此时 prompt 参数传空串 */
  portrait?: { description: string; style: string }
}

interface GenerationJob {
  id: string
  status: string
  progress: number
  /** 最终生效的提示词（portrait 模式由后端拼装返回） */
  prompt?: string
  result?: { urls?: string[]; thumbnailUrls?: string[] }
  error?: string | null
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  return apiRequest<T>(path, init)
}

/** 发起图片创建任务，返回任务 id 与最终生效的提示词（portrait 模式由后端拼装） */
export async function createImageTask(
  prompt: string,
  options: ImageTaskOptions = {},
): Promise<{ id: string; prompt?: string }> {
  const data = await request<GenerationJob>('/generations/images', {
    method: 'POST',
    body: JSON.stringify({
      prompt,
      size: options.size ?? '1024x1024',
      quality: options.quality ?? 'auto',
      n: options.n ?? 1,
      purpose: 'digital_human',
      ...(options.portrait ? { portrait: options.portrait } : {}),
      ...(options.image
        ? { images: Array.isArray(options.image) ? options.image : [options.image] }
        : {}),
    }),
  })
  return { id: data.id, prompt: data.prompt }
}

export interface WaitForImageOptions {
  /** @deprecated 周期由统一调度器管理，保留仅为兼容旧调用签名 */
  intervalMs?: number
  timeoutMs?: number
  signal?: AbortSignal
}

// 后端在供应商受理满10分钟时判失败；前端多留一分钟给最后一次状态轮询和结果解析，
// 避免供应商耗时5–10分钟时沿用旧的5分钟窗口而误报超时。
export const DEFAULT_IMAGE_WAIT_TIMEOUT_MS = 11 * 60_000

/** 轮询直至任务完成，返回首张图片地址（经统一轮询调度器，全前端共享一个 3s tick） */
export async function waitForImageAsset(
  taskId: string,
  {
    intervalMs: _intervalMs = 3000,
    timeoutMs = DEFAULT_IMAGE_WAIT_TIMEOUT_MS,
    signal,
  }: WaitForImageOptions = {},
): Promise<{ url: string; thumbnailUrl?: string }> {
  void _intervalMs // 周期由统一调度器管理，保留参数仅为兼容旧调用签名
  return watchGenerationJob<{ url: string; thumbnailUrl?: string }>(taskId, {
    signal,
    timeoutMs,
    failureMessage: '图片生成失败',
    timeoutMessage: '图片生成超时，请稍后重试',
    select: (snapshot: GenerationJobSnapshot) => {
      const result = snapshot.result as { urls?: string[]; thumbnailUrls?: string[] } | undefined
      const url = result?.urls?.[0]
      if (!url) throw new Error('任务成功但未返回图片地址')
      return { url, thumbnailUrl: result?.thumbnailUrls?.[0] }
    },
  })
}

/** 一步到位：发起任务并轮询取回图片地址 */
export async function generateImage(prompt: string, options?: ImageTaskOptions): Promise<string> {
  const task = await createImageTask(prompt, options)
  return (await waitForImageAsset(task.id)).url
}

export async function generateImageAsset(
  prompt: string,
  options?: ImageTaskOptions,
  onTaskCreated?: (taskId: string) => void,
): Promise<{ url: string; thumbnailUrl?: string; prompt?: string }> {
  const task = await createImageTask(prompt, options)
  onTaskCreated?.(task.id)
  const asset = await waitForImageAsset(task.id)
  return { ...asset, prompt: task.prompt }
}

/** 按后端注册中心模板拼装定妆照提示词（不调模型；草稿恢复与重生兜底用） */
export async function fetchPortraitPrompt(description: string, style: string): Promise<string> {
  const data = await request<{ prompt: string }>('/generations/images/portrait-prompt', {
    method: 'POST',
    body: JSON.stringify({ description, style }),
  })
  return data.prompt
}

/** 获取系统人物三视图模板（用于生成/重生的参考图） */
let _templateAvatar: string | null = null
export function setTemplateAvatar(url: string) {
  _templateAvatar = url
}
export function getTemplateAvatar(): string | null {
  return _templateAvatar
}

/** 生成结果已经由后端落入本地存储或 TOS，无需浏览器二次下载。 */
export async function localizeImage(id: string, url: string): Promise<string> {
  void id
  return url
}
