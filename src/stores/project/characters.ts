import type { DigitalHuman } from '../../types'
import * as api from '../../api/domain'
import * as imageGen from '../../api/imageGen'
import { nextId } from '../../utils/id'
import { reportApiError } from '../../errorBus'
import {
  savePendingDhDraft,
  clearPendingDhDraft,
  readPendingDhDraft,
  FALLBACK_STYLE,
} from './shared'
import type { ProjectContext } from './contracts'

export const charactersActions = {
  /** 加入/移出全局角色阵容；移出时同步从所有分镜的出演角色中移除，保证全局统一 */
  toggleCast(digitalHumanId: string) {
    const idx = this.castIds.indexOf(digitalHumanId)
    if (idx >= 0) {
      this.castIds.splice(idx, 1)
      this.lines.forEach((l) => {
        const i = l.digitalHumanIds.indexOf(digitalHumanId)
        if (i >= 0) l.digitalHumanIds.splice(i, 1)
      })
    } else {
      this.castIds.push(digitalHumanId)
    }
    if (this.activeTaskId) void api.updateTaskCast(this.activeTaskId, this.castIds)
    this.lines.forEach(
      (line) => void api.updateStoryboardLine(line.id, { digital_human_ids: line.digitalHumanIds }),
    )
  },

  /** 数字人落库：确保风格存在 → 创建记录 → 更新本地列表（AI 生成 / 自定义上传 / 刷新恢复共用） */
  async _finalizeDigitalHuman(input: {
    name: string
    style: string
    description: string
    avatar: string
    thumbnail?: string
    avatarPrompt: string
    source: 'uploaded' | 'generated'
    styleId?: string
  }): Promise<DigitalHuman> {
    let styleId = input.styleId ?? this.dhStyleIds[input.style]
    if (!styleId) {
      const style = await api.createDigitalHumanStyle(input.style)
      styleId = style.id
      this.dhStyleIds[input.style] = style.id
      if (!this.dhStyles.includes(input.style)) this.dhStyles.push(input.style)
    }
    const dh = await api.createDigitalHuman({
      name: input.name,
      styleId,
      description: input.description,
      avatar: input.avatar,
      thumbnail: input.thumbnail,
      avatarPrompt: input.avatarPrompt,
      source: input.source,
    })
    const existing = this.digitalHumans.findIndex((item) => item.id === dh.id)
    if (existing >= 0) this.digitalHumans.splice(existing, 1, dh)
    else this.digitalHumans.push(dh)
    this.ensureDhStyle(dh.style)
    return dh
  },

  /** 刷新/重开后恢复上次未完成的数字人生成：任务还在跑则恢复等待态续跑，已跑完则直接补建落库 */
  async resumePendingDigitalHuman() {
    const draft = readPendingDhDraft()
    if (!draft) return
    this.dhGenerating = true
    try {
      const generated = await imageGen.waitForImageAsset(draft.jobId)
      await this._finalizeDigitalHuman({
        name: draft.name,
        style: draft.style,
        description: draft.description,
        avatar: generated.url,
        thumbnail: generated.thumbnailUrl,
        avatarPrompt: await imageGen.fetchPortraitPrompt(draft.description, draft.style),
        source: draft.mode,
        styleId: draft.styleId,
      })
    } catch (error) {
      reportApiError(error, '数字人生成失败')
    } finally {
      clearPendingDhDraft()
      this.dhGenerating = false
    }
  },

  /** 调用真实异步生图接口生成数字人形象，图片本地化存储后加入资产库 */
  async generateDigitalHuman(input: {
    name: string
    style: string
    description: string
    referenceImage?: string
  }): Promise<DigitalHuman> {
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
        (jobId) =>
          savePendingDhDraft({
            mode: 'generated',
            jobId,
            name: input.name,
            style: input.style,
            description: input.description,
          }),
      )
      const avatar = await imageGen.localizeImage(id, generated.url)
      return await this._finalizeDigitalHuman({
        name: input.name,
        style: input.style,
        description: input.description,
        avatar,
        thumbnail: generated.thumbnailUrl,
        avatarPrompt: generated.prompt ?? '',
        source: 'generated',
      })
    } finally {
      clearPendingDhDraft()
      this.dhGenerating = false
    }
  },

  async addCustomDigitalHuman(input: {
    name: string
    style: string
    description?: string
    avatar?: string
  }): Promise<DigitalHuman> {
    this.dhGenerating = true
    this.dhGeneratingPhase = input.avatar ? 'uploading' : 'generating'
    try {
      let styleId = this.dhStyleIds[input.style]
      if (!styleId) {
        const style = await api.createDigitalHumanStyle(input.style)
        styleId = style.id
        this.dhStyleIds[input.style] = style.id
        if (!this.dhStyles.includes(input.style)) this.dhStyles.push(input.style)
      }
      const reference = input.avatar
        ? await api.uploadDataUrl(input.avatar, `${nextId('reference')}.jpg`)
        : undefined
      this.dhGeneratingPhase = 'generating'
      const generated = await imageGen.generateImageAsset(
        '',
        {
          size: '1024x1536',
          quality: 'auto',
          portrait: { description: input.description?.trim() || '', style: input.style },
          ...(reference ? { image: reference.url } : {}),
        },
        (jobId) =>
          savePendingDhDraft({
            mode: 'uploaded',
            jobId,
            name: input.name,
            style: input.style,
            description: input.description ?? '',
            styleId,
          }),
      )
      return await this._finalizeDigitalHuman({
        name: input.name,
        style: input.style,
        description: input.description ?? '',
        avatar: generated.url,
        thumbnail: generated.thumbnailUrl,
        avatarPrompt: generated.prompt ?? '',
        source: 'uploaded',
        styleId,
      })
    } finally {
      clearPendingDhDraft()
      this.dhGenerating = false
      this.dhGeneratingPhase = ''
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
  renameDhStyle(oldName: string, newName: string): boolean {
    if (this.systemDhStyles.includes(oldName)) return false
    const s = newName.trim()
    if (!s || s === '全部' || s === oldName) return false
    const idx = this.dhStyles.indexOf(oldName)
    // 分类可能仅来自兜底合并（在用但未登记），此时也允许重命名
    if (idx < 0 && !this.digitalHumans.some((d) => d.style === oldName)) return false
    if (idx >= 0) {
      this.dhStyles.includes(s) ? this.dhStyles.splice(idx, 1) : (this.dhStyles[idx] = s)
    } else if (!this.dhStyles.includes(s)) {
      this.dhStyles.push(s)
    }
    let touched = false
    this.digitalHumans.forEach((d) => {
      if (d.style === oldName) {
        d.style = s
        touched = true
      }
    })
    if (touched)
      this.digitalHumans
        .filter((d) => d.style === s && !d.readOnly)
        .forEach((d) => void api.updateDigitalHuman(d.id, { style_id: this.dhStyleIds[s] }))
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
  updateDigitalHuman(
    id: string,
    patch: Partial<Pick<DigitalHuman, 'name' | 'style' | 'description' | 'avatarPrompt'>>,
  ) {
    const dh = this.digitalHumans.find((d) => d.id === id)
    if (!dh || dh.readOnly) return
    Object.assign(dh, patch)
    if (!dh.readOnly)
      void api.updateDigitalHuman(id, {
        name: patch.name,
        style_id: patch.style ? this.dhStyleIds[patch.style] : undefined,
        description: patch.description,
        avatar_prompt: patch.avatarPrompt,
      })
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
