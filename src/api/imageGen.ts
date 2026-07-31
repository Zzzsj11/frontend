/** 异步生图真实接口（api-aigc.fzyinghe.com）
 *  - POST /image/generation/tasks 发起图片创建任务（带 image 字段则为图生图）
 *  - GET  /image/generation/tasks/{taskId} 轮询任务结果
 *  开发环境经 vite 代理 /aigc 转发，规避浏览器跨域限制（见 vite.config.ts） */

const BASE = '/aigc'
const API_KEY = 'yh-tc6lxzhy3hjnzrj59qr4d8y213fvyixwv61t9tcq0dsbsot'

interface ApiResponse<T> {
  code: number
  msg: string
  data: T
}

export interface ImageTaskOptions {
  /** WIDTHxHEIGHT，宽 × 高必须小于 8,294,400，默认 1024x1024 */
  size?: string
  quality?: 'auto' | 'low' | 'medium' | 'high'
  /** 生成图片数量 1-4 */
  n?: number
  /** 图片 URL（或数组）：传入即按图生图处理，不传为文生图 */
  image?: string | string[]
}

interface CreatedTask {
  taskId: string
  status: string
}

interface TaskResult {
  taskId: string
  status: string
  progress?: number
  resultUrls?: string[]
  resultUrl?: string
  failReason?: string | null
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      'x-api-key': API_KEY,
      'Content-Type': 'application/json',
      Accept: '*/*',
      ...init?.headers,
    },
  })
  if (!res.ok) throw new Error(`生图接口请求失败（HTTP ${res.status}）`)
  const body = (await res.json()) as ApiResponse<T>
  if (body.code !== 200) throw new Error(body.msg || `生图接口错误（code=${body.code}）`)
  return body.data
}

/** 发起图片创建任务，返回 taskId */
export async function createImageTask(prompt: string, options: ImageTaskOptions = {}): Promise<string> {
  const data = await request<CreatedTask>('/image/generation/tasks', {
    method: 'POST',
    body: JSON.stringify({
      model: 'gpt-image-2',
      prompt,
      size: options.size ?? '1024x1024',
      quality: options.quality ?? 'auto',
      n: options.n ?? 1,
      ...(options.image ? { image: options.image } : {}),
    }),
  })
  return data.taskId
}

/** 查询任务状态 */
export function getImageTask(taskId: string): Promise<TaskResult> {
  return request<TaskResult>(`/image/generation/tasks/${taskId}`)
}

/** 轮询直至任务完成，返回首张图片地址 */
export async function waitForImage(
  taskId: string,
  { intervalMs = 3000, timeoutMs = 300_000 } = {},
): Promise<string> {
  const deadline = Date.now() + timeoutMs
  for (;;) {
    const task = await getImageTask(taskId)
    const status = (task.status ?? '').toUpperCase()
    if (status === 'SUCCESS') {
      const url = task.resultUrl ?? task.resultUrls?.[0]
      if (!url) throw new Error('任务成功但未返回图片地址')
      return url
    }
    if (status.includes('FAIL')) throw new Error(task.failReason || '图片生成失败')
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

/** 把远程签名图片 URL 本地化存储（dev server 下载保存到 public/digital-humans/），
 *  失败时降级返回原始远程地址，保证功能可用 */
export async function localizeImage(id: string, url: string): Promise<string> {
  try {
    const res = await fetch('/local-store/digital-human', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id, url }),
    })
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    const body = (await res.json()) as { code: number; path?: string; msg?: string }
    if (body.code !== 200 || !body.path) throw new Error(body.msg || '本地化存储失败')
    return body.path
  } catch (err) {
    console.warn('[localizeImage] 本地化存储失败，回退使用远程地址：', err)
    return url
  }
}