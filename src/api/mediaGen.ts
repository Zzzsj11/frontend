import type { ShotGenOptions } from '../types'
import type { ImageModelId } from '../generationModels'
import { apiRequest } from './client'

interface GenerationJob<T = Record<string, unknown>> {
  id: string
  status: 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled'
  progress: number
  result?: T
  error?: string | null
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  return apiRequest<T>(path, init)
}

export async function waitForJob<T>(id: string, timeoutMs = 660_000): Promise<T> {
  const deadline = Date.now() + timeoutMs
  for (;;) {
    // 每 3 秒轮询直到生成完成（最长 11 分钟）：打 X-Polling 标记，后端全量日志跳过
    const job = await request<GenerationJob<T>>(`/generations/${id}`, {
      headers: { 'X-Polling': '1' },
    })
    if (job.status === 'succeeded' && job.result) return job.result
    if (job.status === 'failed' || job.status === 'cancelled')
      throw new Error(job.error || '生成失败')
    if (Date.now() >= deadline) throw new Error('生成超时，请稍后重试')
    await new Promise((resolve) => setTimeout(resolve, 3000))
  }
}

export async function generateScene(
  prompt: string,
  projectTaskId?: string,
  storyboardLineId?: string,
  ratio: ShotGenOptions['ratio'] = '16:9',
  model?: ImageModelId,
  resolution: ShotGenOptions['resolution'] = '720p',
): Promise<{ imageUrl: string; thumbnailUrl?: string }> {
  const size =
    ratio === '9:16'
      ? '1024x1536'
      : ratio === '1:1'
        ? '1024x1024'
        : ratio === '4:3'
          ? '1365x1024'
          : '1536x1024'
  const quality = resolution === '480p' ? 'low' : resolution === '1080p' ? 'high' : 'medium'
  const job = await request<GenerationJob>('/generations/images', {
    method: 'POST',
    body: JSON.stringify({
      prompt,
      size,
      quality,
      n: 1,
      model,
      purpose: 'scene',
      project_task_id: projectTaskId,
      storyboard_line_id: storyboardLineId,
    }),
  })
  const result = await waitForJob<{ urls: string[]; thumbnailUrls?: string[] }>(job.id)
  if (!result.urls?.[0]) throw new Error('场景生成成功但没有图片')
  return { imageUrl: result.urls[0], thumbnailUrl: result.thumbnailUrls?.[0] }
}

export async function generateShotVideo(
  prompt: string,
  referenceImageUrl: string | undefined,
  characterImageUrls: string[],
  options: ShotGenOptions,
  projectTaskId?: string,
  storyboardLineId?: string,
): Promise<{ coverUrl: string; coverThumbnailUrl?: string; videoUrl: string; duration: number }> {
  const imageUrls = [referenceImageUrl, ...characterImageUrls].filter(Boolean) as string[]
  const job = await request<GenerationJob>('/generations/videos', {
    method: 'POST',
    body: JSON.stringify({
      prompt,
      duration: options.duration,
      ratio: options.ratio,
      resolution: options.resolution,
      model: options.videoModel,
      image_urls: imageUrls,
      generate_audio: false,
      project_task_id: projectTaskId,
      storyboard_line_id: storyboardLineId,
    }),
  })
  const result = await waitForJob<{
    coverUrl?: string
    coverThumbnailUrl?: string
    videoUrl: string
    duration: number
  }>(job.id)
  return {
    coverUrl: result.coverUrl || referenceImageUrl || '',
    coverThumbnailUrl: result.coverThumbnailUrl,
    videoUrl: result.videoUrl,
    duration: result.duration,
  }
}
