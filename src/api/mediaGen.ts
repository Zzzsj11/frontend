import type { ShotGenOptions } from '../types'
import type { ImageModelId } from '../generationModels'
import { apiRequest } from './client'
import { watchGenerationJob, type GenerationJobSnapshot } from '../utils/generationPoller'

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

export interface WaitForJobOptions {
  /** 切换子项目时经统一注册表 abort，轮询立即停止（后端任务照跑，切回后恢复） */
  signal?: AbortSignal
}

/** 经统一轮询调度器等待生成任务完成（全前端共享一个 3s tick，替代独立循环） */
export async function waitForJob<T>(
  id: string,
  timeoutMs = 660_000,
  options: WaitForJobOptions = {},
): Promise<T> {
  return watchGenerationJob<T>(id, {
    signal: options.signal,
    timeoutMs,
    select: (snapshot: GenerationJobSnapshot) => snapshot.result as T,
  })
}

export async function generateScene(
  prompt: string,
  projectTaskId?: string,
  storyboardLineId?: string,
  ratio: ShotGenOptions['ratio'] = '16:9',
  model?: ImageModelId,
  resolution: ShotGenOptions['resolution'] = '720p',
  signal?: AbortSignal,
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
  const result = await waitForJob<{ urls: string[]; thumbnailUrls?: string[] }>(job.id, 660_000, {
    signal,
  })
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
  signal?: AbortSignal,
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
      generate_audio: options.generateAudio ?? false,
      watermark: options.watermark ?? false,
      project_task_id: projectTaskId,
      storyboard_line_id: storyboardLineId,
    }),
  })
  const result = await waitForJob<{
    coverUrl?: string
    coverThumbnailUrl?: string
    videoUrl: string
    duration: number
  }>(job.id, 660_000, { signal })
  return {
    coverUrl: result.coverUrl || referenceImageUrl || '',
    coverThumbnailUrl: result.coverThumbnailUrl,
    videoUrl: result.videoUrl,
    duration: result.duration,
  }
}
