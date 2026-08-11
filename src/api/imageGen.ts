/** 图片生成由 Python 后端代理，第三方密钥不会再暴露到浏览器。 */

import { apiRequest } from './client'

export interface ImageTaskOptions {
  /** WIDTHxHEIGHT，宽 × 高必须小于 8,294,400，默认 1024x1024 */
  size?: string
  quality?: 'auto' | 'low' | 'medium' | 'high'
  /** 生成图片数量 1-4 */
  n?: number
  /** 图片 URL（或数组）：传入即按图生图处理，不传为文生图 */
  image?: string | string[]
}

interface GenerationJob {
  id: string
  status: string
  progress: number
  result?: { urls?: string[]; thumbnailUrls?: string[] }
  error?: string | null
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  return apiRequest<T>(path, init)
}

/** 发起图片创建任务，返回 taskId */
export async function createImageTask(
  prompt: string,
  options: ImageTaskOptions = {},
): Promise<string> {
  const data = await request<GenerationJob>('/generations/images', {
    method: 'POST',
    body: JSON.stringify({
      prompt,
      size: options.size ?? '1024x1024',
      quality: options.quality ?? 'auto',
      n: options.n ?? 1,
      purpose: 'digital_human',
      ...(options.image
        ? { images: Array.isArray(options.image) ? options.image : [options.image] }
        : {}),
    }),
  })
  return data.id
}

/** 查询任务状态 */
export function getImageTask(taskId: string): Promise<GenerationJob> {
  return request<GenerationJob>(`/generations/${taskId}`)
}

/** 轮询直至任务完成，返回首张图片地址 */
export async function waitForImageAsset(
  taskId: string,
  { intervalMs = 3000, timeoutMs = 300_000 } = {},
): Promise<{ url: string; thumbnailUrl?: string }> {
  const deadline = Date.now() + timeoutMs
  for (;;) {
    const task = await getImageTask(taskId)
    const status = (task.status ?? '').toLowerCase()
    if (status === 'succeeded') {
      const url = task.result?.urls?.[0]
      if (!url) throw new Error('任务成功但未返回图片地址')
      return { url, thumbnailUrl: task.result?.thumbnailUrls?.[0] }
    }
    if (status === 'failed' || status === 'cancelled') throw new Error(task.error || '图片生成失败')
    if (Date.now() > deadline) throw new Error('图片生成超时，请稍后重试')
    await new Promise((r) => setTimeout(r, intervalMs))
  }
}

/** 一步到位：发起任务并轮询取回图片地址 */
export async function generateImage(prompt: string, options?: ImageTaskOptions): Promise<string> {
  const taskId = await createImageTask(prompt, options)
  return (await waitForImageAsset(taskId)).url
}

export async function generateImageAsset(
  prompt: string,
  options?: ImageTaskOptions,
  onTaskCreated?: (taskId: string) => void,
): Promise<{ url: string; thumbnailUrl?: string }> {
  const taskId = await createImageTask(prompt, options)
  onTaskCreated?.(taskId)
  return waitForImageAsset(taskId)
}

/** 数字人定妆照提示词模板（与批量生成脚本 scripts/generate-digital-humans.mjs 保持一致） */
export function buildPortraitPrompt(description: string, style: string): string {
  return `MV 数字人角色三视图设定板。角色描述：${description || '依据参考图保持人物身份特征'}。视觉风格：${style || '电影写实'}。横版 16:9，单一角色，必须在同一张图中从左到右完整展示正面、90度侧面、背面三个人物全身视图；三视图必须保持同一张脸、同一发型、同一体型、同一服装、同一配饰和完全一致的色彩材质。人物从头顶到鞋底完整可见，站姿自然中性，比例准确，视图之间留有均匀间距。浅灰或米白纯色摄影棚背景，均匀柔光，无场景、无道具、无文字、无标签、无水印、无 Logo、无边框。禁止裁切身体，禁止额外人物，禁止把三个视图生成成不同角色。高质量角色设计参考图，可直接用于后续 MV 分镜人物一致性参考。`
}

/** 生成结果已经由后端落入本地存储或 TOS，无需浏览器二次下载。 */
export async function localizeImage(id: string, url: string): Promise<string> {
  void id
  return url
}
