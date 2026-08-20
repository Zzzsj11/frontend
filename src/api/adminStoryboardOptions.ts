import { apiRequest } from './client'

/** 通用分镜选项类别：genre 为三级分类树，其余为平铺列表 */
export type StoryboardOptionKind = 'genre' | 'season' | 'age_group' | 'visual_style'

/** 管理后台选项行（平铺，前端按 parentId 组树） */
export interface StoryboardOptionItem {
  id: string
  kind: StoryboardOptionKind
  parentId: string | null
  name: string
  sortOrder: number
  castPolicy: 'required' | 'optional_random' | null
}

export const listStoryboardOptions = (kind: StoryboardOptionKind) =>
  apiRequest<StoryboardOptionItem[]>(`/admin/storyboard-options?kind=${kind}`)

export const createStoryboardOption = (input: {
  kind: StoryboardOptionKind
  parentId?: string | null
  name: string
  sortOrder?: number
  castPolicy?: 'required' | 'optional_random' | null
}) =>
  apiRequest<StoryboardOptionItem>('/admin/storyboard-options', {
    method: 'POST',
    body: JSON.stringify({
      kind: input.kind,
      parent_id: input.parentId ?? null,
      name: input.name,
      ...(input.sortOrder !== undefined ? { sort_order: input.sortOrder } : {}),
      ...(input.castPolicy !== undefined ? { cast_policy: input.castPolicy } : {}),
    }),
  })

export const updateStoryboardOption = (
  id: string,
  patch: {
    name?: string
    sortOrder?: number
    castPolicy?: 'required' | 'optional_random' | null
  },
) =>
  apiRequest<StoryboardOptionItem>(`/admin/storyboard-options/${encodeURIComponent(id)}`, {
    method: 'PATCH',
    body: JSON.stringify({
      ...(patch.name !== undefined ? { name: patch.name } : {}),
      ...(patch.sortOrder !== undefined ? { sort_order: patch.sortOrder } : {}),
      ...(patch.castPolicy !== undefined ? { cast_policy: patch.castPolicy } : {}),
    }),
  })

export const deleteStoryboardOption = (id: string) =>
  apiRequest<{ ok: boolean; cascadeCount: number }>(
    `/admin/storyboard-options/${encodeURIComponent(id)}`,
    { method: 'DELETE' },
  )
