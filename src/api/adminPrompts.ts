import { apiRequest } from './client'

/** 提示词版本摘要（列表与详情共用） */
export interface PromptVersionSummary {
  id: string
  version: number
  status: 'draft' | 'published' | 'archived'
  changeNote: string
  createdBy: string
  publishedAt: string | null
  createdAt: string | null
}

/** 提示词模板列表行 */
export interface PromptTemplateRow {
  id: string
  key: string
  name: string
  description: string
  engine: string
  format: 'text' | 'json'
  variables: Record<string, string>
  requiredFragments: string[]
  currentVersion: PromptVersionSummary | null
  updatedAt: string | null
}

/** 模板详情：全部版本（含内容）+ 内置默认内容 */
export interface PromptDetail extends Omit<PromptTemplateRow, 'currentVersion' | 'updatedAt'> {
  currentVersionId: string | null
  versions: (PromptVersionSummary & { content: string })[]
  defaultContent: string | null
}

/** 试渲染报告 */
export interface PromptPreviewResult {
  rendered: string
  usedVariables: string[]
  missingVariables: string[]
  undeclaredVariables: string[]
  missingFragments: string[]
  jsonError: string
}

export const listPrompts = () => apiRequest<PromptTemplateRow[]>('/admin/prompts')

export const getPromptDetail = (key: string) =>
  apiRequest<PromptDetail>(`/admin/prompts/${encodeURIComponent(key)}`)

export const createPromptDraft = (key: string, content: string, changeNote: string) =>
  apiRequest<{ id: string; version: number }>(
    `/admin/prompts/${encodeURIComponent(key)}/versions`,
    {
      method: 'POST',
      body: JSON.stringify({ content, change_note: changeNote }),
    },
  )

export const publishPrompt = (key: string, versionId: string) =>
  apiRequest<{ ok: boolean; version: number }>(
    `/admin/prompts/${encodeURIComponent(key)}/publish`,
    {
      method: 'POST',
      body: JSON.stringify({ version_id: versionId }),
    },
  )

export const previewPrompt = (key: string, content: string, variables: Record<string, string>) =>
  apiRequest<PromptPreviewResult>(`/admin/prompts/${encodeURIComponent(key)}/preview`, {
    method: 'POST',
    body: JSON.stringify({ content, variables }),
  })

export const deletePromptDraft = (key: string, versionId: string) =>
  apiRequest<{ ok: boolean }>(
    `/admin/prompts/${encodeURIComponent(key)}/versions/${encodeURIComponent(versionId)}`,
    { method: 'DELETE' },
  )
