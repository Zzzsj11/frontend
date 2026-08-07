import type { ShotGenOptions } from '../types'

interface GenerationJob<T = Record<string, unknown>> {
  id: string
  status: 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled'
  progress: number
  result?: T
  error?: string | null
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  })
  const body = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(body.detail || `请求失败（HTTP ${response.status}）`)
  return body as T
}

async function waitForJob<T>(id: string, timeoutMs = 660_000): Promise<T> {
  const deadline = Date.now() + timeoutMs
  for (;;) {
    const job = await request<GenerationJob<T>>(`/generations/${id}`)
    if (job.status === 'succeeded' && job.result) return job.result
    if (job.status === 'failed' || job.status === 'cancelled') throw new Error(job.error || '生成失败')
    if (Date.now() >= deadline) throw new Error('生成超时，请稍后重试')
    await new Promise((resolve) => setTimeout(resolve, 3000))
  }
}

export async function generateScene(prompt: string): Promise<{ imageUrl: string }> {
  const job = await request<GenerationJob>('/generations/images', {
    method: 'POST',
    body: JSON.stringify({ prompt, size: '1536x1024', quality: 'auto', n: 1 }),
  })
  const result = await waitForJob<{ urls: string[] }>(job.id)
  if (!result.urls?.[0]) throw new Error('场景生成成功但没有图片')
  return { imageUrl: result.urls[0] }
}

export async function generateShotVideo(
  prompt: string,
  referenceImageUrl: string | undefined,
  options: ShotGenOptions,
): Promise<{ coverUrl: string; videoUrl: string; duration: number }> {
  const job = await request<GenerationJob>('/generations/videos', {
    method: 'POST',
    body: JSON.stringify({
      prompt,
      duration: options.duration,
      ratio: options.ratio,
      image_urls: referenceImageUrl ? [referenceImageUrl] : [],
      generate_audio: false,
    }),
  })
  const result = await waitForJob<{ coverUrl?: string; videoUrl: string; duration: number }>(job.id)
  return {
    coverUrl: result.coverUrl || referenceImageUrl || '',
    videoUrl: result.videoUrl,
    duration: result.duration,
  }
}
