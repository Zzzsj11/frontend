import type { DigitalHuman } from '../../types'
import * as api from '../../api/domain'
import * as imageGen from '../../api/imageGen'
import { nextId } from '../../utils/id'
import { GenerationJobFailed } from '../../utils/generationPoller'
import { currentSession } from '../../api/client'
import { ApiError, reportApiError } from '../../errorBus'
import {
  savePendingDhDraft,
  clearPendingDhDraft,
  readPendingDhDraft,
  FALLBACK_STYLE,
} from './shared'
import type { ProjectContext } from './contracts'

const terminalPortraitError = (error: unknown) =>
  error instanceof GenerationJobFailed || (error instanceof ApiError && error.status === 410)

export const charactersActions = {
  /** 加入/移出全局角色阵容；移出时同步从所有分镜的出演角色中移除，保证全局统一 */
  async toggleCast(digitalHumanId: string) {
    if (this.castSaving) return
    const taskId = this.activeTaskId
    const session = currentSession()
    const removing = this.castIds.includes(digitalHumanId)
    const ids = removing
      ? this.castIds.filter((id) => id !== digitalHumanId)
      : [...this.castIds, digitalHumanId]
    this.castSaving = true
    try {
      if (taskId) await api.updateTaskCast(taskId, ids)
      if (session.aborted || this.activeTaskId !== taskId) return
      this.castIds = ids
      if (removing)
        for (const line of this.lines)
          line.digitalHumanIds = line.digitalHumanIds.filter((id) => id !== digitalHumanId)
    } catch (error) {
      if (!session.aborted) reportApiError(error, '保存人物阵容失败')
    } finally {
      if (!session.aborted) this.castSaving = false
    }
  },

  /** 数字人落库：确保风格存在 → 创建记录 → 更新本地列表（AI 生成 / 自定义上传 / 刷新恢复共用） */
  async _finalizeDigitalHuman(input: {
    sourceJobId?: string
    name: string
    style: string
    description: string
    avatar: string
    thumbnail?: string
    avatarPrompt: string
    source: 'uploaded' | 'generated'
    styleId?: string
  }): Promise<DigitalHuman> {
    const session = currentSession()
    let styleId = input.styleId ?? this.dhStyleIds[input.style]
    if (!styleId) {
      const style = await api.createDigitalHumanStyle(input.style)
      session.throwIfAborted()
      styleId = style.id
      this.dhStyleIds[input.style] = style.id
      if (!this.dhStyles.includes(input.style)) this.dhStyles.push(input.style)
    }
    const dh = await api.createDigitalHuman({
      name: input.name,
      sourceJobId: input.sourceJobId,
      styleId,
      description: input.description,
      avatar: input.avatar,
      thumbnail: input.thumbnail,
      avatarPrompt: input.avatarPrompt,
      source: input.source,
    })
    session.throwIfAborted()
    const existing = this.digitalHumans.findIndex((item) => item.id === dh.id)
    if (existing >= 0) this.digitalHumans.splice(existing, 1, dh)
    else this.digitalHumans.push(dh)
    this.ensureDhStyle(dh.style)
    return dh
  },

  /** 刷新/重开后恢复上次未完成的数字人生成：任务还在跑则恢复等待态续跑，已跑完则直接补建落库 */
  async resumePendingDigitalHuman() {
    const session = currentSession()
    const draft = readPendingDhDraft()
    if (!draft) return
    this.dhGenerating = true
    try {
      const generated = await imageGen.waitForImageAsset(draft.jobId)
      session.throwIfAborted()
      const avatarPrompt = await imageGen.fetchPortraitPrompt(draft.description, draft.style)
      session.throwIfAborted()
      await this._finalizeDigitalHuman({
        sourceJobId: draft.jobId,
        name: draft.name,
        style: draft.style,
        description: draft.description,
        avatar: generated.url,
        thumbnail: generated.thumbnailUrl,
        avatarPrompt,
        source: draft.mode,
        styleId: draft.styleId,
      })
      if (!session.aborted) clearPendingDhDraft(draft.jobId)
    } catch (error) {
      if (session.aborted) return
      if (terminalPortraitError(error)) clearPendingDhDraft(draft.jobId)
      reportApiError(error, '数字人生成失败')
    } finally {
      if (!session.aborted) this.dhGenerating = false
    }
  },

  /** 调用真实异步生图接口生成数字人形象，图片本地化存储后加入资产库 */
  async generateDigitalHuman(input: {
    name: string
    style: string
    description: string
    referenceImage?: string
  }): Promise<DigitalHuman> {
    const session = currentSession()
    let sourceJobId: string | undefined
    this.dhGenerating = true
    try {
      const id = nextId('dh')
      const generated = await imageGen.generateImageAsset(
        '',
        {
          size: '1024x1536',
          quality: 'auto',
          portrait: { description: input.description, style: input.style },
          ...(input.referenceImage ? { image: input.referenceImage } : {}),
        },
        // 任务创建后先留草稿：页面刷新后可据此恢复等待态并补建数字人
        (jobId) => {
          sourceJobId = jobId
          if (!session.aborted)
            savePendingDhDraft({
              mode: 'generated',
              jobId,
              name: input.name,
              style: input.style,
              description: input.description,
            })
        },
      )
      const avatar = await imageGen.localizeImage(id, generated.url)
      session.throwIfAborted()
      const human = await this._finalizeDigitalHuman({
        sourceJobId,
        name: input.name,
        style: input.style,
        description: input.description,
        avatar,
        thumbnail: generated.thumbnailUrl,
        avatarPrompt: generated.prompt ?? '',
        source: 'generated',
      })
      if (!session.aborted && sourceJobId) clearPendingDhDraft(sourceJobId)
      return human
    } catch (error) {
      if (!session.aborted && sourceJobId && terminalPortraitError(error))
        clearPendingDhDraft(sourceJobId)
      throw error
    } finally {
      if (!session.aborted) this.dhGenerating = false
    }
  },

  async addCustomDigitalHuman(input: {
    name: string
    style: string
    description?: string
    avatar?: string
  }): Promise<DigitalHuman> {
    const session = currentSession()
    let sourceJobId: string | undefined
    this.dhGenerating = true
    this.dhGeneratingPhase = input.avatar ? 'uploading' : 'generating'
    try {
      let styleId = this.dhStyleIds[input.style]
      if (!styleId) {
        const style = await api.createDigitalHumanStyle(input.style)
        session.throwIfAborted()
        styleId = style.id
        this.dhStyleIds[input.style] = style.id
        if (!this.dhStyles.includes(input.style)) this.dhStyles.push(input.style)
      }
      const reference = input.avatar
        ? await api.uploadDataUrl(input.avatar, `${nextId('reference')}.jpg`)
        : undefined
      session.throwIfAborted()
      this.dhGeneratingPhase = 'generating'
      const generated = await imageGen.generateImageAsset(
        '',
        {
          size: '1024x1536',
          quality: 'auto',
          portrait: { description: input.description?.trim() || '', style: input.style },
          ...(reference ? { image: reference.url } : {}),
        },
        (jobId) => {
          sourceJobId = jobId
          if (!session.aborted)
            savePendingDhDraft({
              mode: 'uploaded',
              jobId,
              name: input.name,
              style: input.style,
              description: input.description ?? '',
              styleId,
            })
        },
      )
      session.throwIfAborted()
      const human = await this._finalizeDigitalHuman({
        sourceJobId,
        name: input.name,
        style: input.style,
        description: input.description ?? '',
        avatar: generated.url,
        thumbnail: generated.thumbnailUrl,
        avatarPrompt: generated.prompt ?? '',
        source: 'uploaded',
        styleId,
      })
      if (!session.aborted && sourceJobId) clearPendingDhDraft(sourceJobId)
      return human
    } catch (error) {
      if (!session.aborted && sourceJobId && terminalPortraitError(error))
        clearPendingDhDraft(sourceJobId)
      throw error
    } finally {
      if (!session.aborted) {
        this.dhGenerating = false
        this.dhGeneratingPhase = ''
      }
    }
  },

  // ---------- 风格分类增删改查 ----------
  /** 登记某风格到分类列表（生成/上传/编辑数字人使用新风格时自动登记） */
  ensureDhStyle(style: string) {
    const s = style.trim()
    if (!s || this.dhStyles.includes(s)) return
    this.dhStyles.push(s)
    void api.createDigitalHumanStyle(s).then((item) => {
      this.dhStyleIds[s] = item.id
    })
  },

  /** 新增风格分类；名称为空或已存在时返回 false */
  addDhStyle(name: string): boolean {
    const s = name.trim()
    if (!s || s === '全部' || this.allDhStyles.includes(s)) return false
    this.dhStyles.push(s)
    void api.createDigitalHumanStyle(s).then((item) => {
      this.dhStyleIds[s] = item.id
    })
    return true
  },

  /** 重命名风格分类：同步更新该分类下所有数字人；目标名已存在时合并到该分类 */
  async renameDhStyle(oldName: string, newName: string): Promise<boolean> {
    const name = newName.trim()
    const id = this.dhStyleIds[oldName]
    if (
      !id ||
      this.systemDhStyles.includes(oldName) ||
      !name ||
      name === '全部' ||
      name === oldName
    )
      return false
    const updated = await api.renameDigitalHumanStyle(id, name)
    this.dhStyles = [
      ...new Set(this.dhStyles.map((style) => (style === oldName ? updated.name : style))),
    ]
    delete this.dhStyleIds[oldName]
    this.dhStyleIds[updated.name] = updated.id
    for (const human of this.digitalHumans)
      if (!human.readOnly && human.style === oldName) human.style = updated.name
    return true
  },

  /** 删除风格分类：该分类下的数字人归入「未分类」 */
  deleteDhStyle(name: string) {
    if (this.systemDhStyles.includes(name)) return
    const idx = this.dhStyles.indexOf(name)
    if (idx >= 0) this.dhStyles.splice(idx, 1)
    let moved = false
    this.digitalHumans.forEach((d) => {
      if (d.style === name) {
        d.style = FALLBACK_STYLE
        moved = true
      }
    })
    if (moved && !this.dhStyles.includes(FALLBACK_STYLE)) this.dhStyles.push(FALLBACK_STYLE)
    const styleId = this.dhStyleIds[name]
    if (styleId) void api.deleteDigitalHumanStyle(styleId)
  },

  /** 编辑数字人基础信息 / 提示词 */
  async updateDigitalHuman(
    id: string,
    patch: Partial<Pick<DigitalHuman, 'name' | 'style' | 'description' | 'avatarPrompt'>>,
  ) {
    const dh = this.digitalHumans.find((d) => d.id === id)
    if (!dh || dh.readOnly) return
    await api.updateDigitalHuman(id, {
      name: patch.name,
      style_id: patch.style ? this.dhStyleIds[patch.style] : undefined,
      description: patch.description,
      avatar_prompt: patch.avatarPrompt,
    })
    Object.assign(dh, patch)
    if (patch.style) this.ensureDhStyle(patch.style)
  },

  /** 删除数字人：同步从全局阵容与所有分镜出演角色中移除 */
  deleteDigitalHuman(id: string) {
    const idx = this.digitalHumans.findIndex((d) => d.id === id)
    if (idx < 0 || this.digitalHumans[idx].readOnly) return
    void api.deleteDigitalHuman(id)
    this.digitalHumans.splice(idx, 1)
    const c = this.castIds.indexOf(id)
    if (c >= 0) this.castIds.splice(c, 1)
    this.lines.forEach((l) => {
      const i = l.digitalHumanIds.indexOf(id)
      if (i >= 0) l.digitalHumanIds.splice(i, 1)
    })
  },

  /** 用（可能已修改的）提示词重新生成数字人形象，成功后本地化存储并替换头像 */
  async regenerateDigitalHumanAvatar(id: string): Promise<void> {
    const dh = this.digitalHumans.find((d) => d.id === id)
    if (!dh || dh.readOnly || this.dhRegeneratingId) return
    this.dhRegeneratingId = id
    try {
      const identityDescription = (dh.description || '').trim()
      const dhRef = dh.originalAvatar || dh.avatar
      const generated = await imageGen.generateImageAsset('', {
        size: '1024x1536',
        quality: 'auto',
        portrait: { description: identityDescription, style: dh.style },
        ...(dhRef ? { image: dhRef } : {}),
      })
      await api.updateDigitalHuman(id, {
        avatar_url: generated.url,
        avatar_thumbnail_url: generated.thumbnailUrl,
        avatar_prompt: generated.prompt || '',
      })
      dh.avatar = generated.thumbnailUrl || generated.url
      dh.originalAvatar = generated.url
      dh.avatarPrompt = generated.prompt || ''
    } finally {
      this.dhRegeneratingId = null
    }
  },
} satisfies ThisType<ProjectContext>
