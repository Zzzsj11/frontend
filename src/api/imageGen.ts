/** 图片生成由 Python 后端代理，第三方密钥不会再暴露到浏览器。 */

const BASE = '/api'

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
  result?: { urls?: string[] }
  error?: string | null
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      Accept: 'application/json',
      ...init?.headers,
    },
  })
  const body = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(body.detail || `后端请求失败（HTTP ${res.status}）`)
  return body as T
}

/** 发起图片创建任务，返回 taskId */
export async function createImageTask(prompt: string, options: ImageTaskOptions = {}): Promise<string> {
  const data = await request<GenerationJob>('/generations/images', {
    method: 'POST',
    body: JSON.stringify({
      prompt,
      size: options.size ?? '1024x1024',
      quality: options.quality ?? 'auto',
      n: options.n ?? 1,
      ...(options.image ? { images: Array.isArray(options.image) ? options.image : [options.image] } : {}),
    }),
  })
  return data.id
}

/** 查询任务状态 */
export function getImageTask(taskId: string): Promise<GenerationJob> {
  return request<GenerationJob>(`/generations/${taskId}`)
}

/** 轮询直至任务完成，返回首张图片地址 */
export async function waitForImage(
  taskId: string,
  { intervalMs = 3000, timeoutMs = 300_000 } = {},
): Promise<string> {
  const deadline = Date.now() + timeoutMs
  for (;;) {
    const task = await getImageTask(taskId)
    const status = (task.status ?? '').toLowerCase()
    if (status === 'succeeded') {
      const url = task.result?.urls?.[0]
      if (!url) throw new Error('任务成功但未返回图片地址')
      return url
    }
    if (status === 'failed' || status === 'cancelled') throw new Error(task.error || '图片生成失败')
    if (Date.now() > deadline) throw new Error('图片生成超时，请稍后重试')
    await new Promise((r) => setTimeout(r, intervalMs))
  }
}

/** 一步到位：发起任务并轮询取回图片地址 */
export async function generateImage(prompt: string, options?: ImageTaskOptions): Promise<string> {
  const taskId = await createImageTask(prompt, options)
  return waitForImage(taskId)
}

/** 数字人定妆照提示词模板（与批量生成脚本 scripts/generate-digital-humans.mjs 保持一致） */
export function buildPortraitPrompt(description: string, style: string): string {
  return `数字人角色定妆照：${description}。风格：${style}。竖版 3:4 半身人像，单人出镜，人物居中，五官清晰，干净纯色背景，摄影棚柔光，高质量细节，不要文字水印`
}

/** 生成结果已经由后端落入本地存储或 TOS，无需浏览器二次下载。 */
export async function localizeImage(id: string, url: string): Promise<string> {
  void id
  return url
}
