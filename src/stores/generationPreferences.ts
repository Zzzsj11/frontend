import { defineStore } from 'pinia'
import { apiRequest } from '../api/client'
const channelRequests = new Map<string, Promise<void>>()

export type GenerationModality = 'text' | 'image' | 'video'
export interface GenerationSelection {
  model: string
  channel: string | null
}
export interface GenerationChannel {
  channel: string
  name: string
  priority: number
  available: boolean
  unavailable_reason: string | null
}
export type GenerationPreferences = Partial<Record<GenerationModality, GenerationSelection>>

export const useGenerationPreferences = defineStore('generationPreferences', {
  state: () => ({
    selections: {} as GenerationPreferences,
    channels: {} as Record<string, GenerationChannel[]>,
    ownerId: '',
    loading: false,
    saving: false,
  }),
  actions: {
    async load(userId: string) {
      if (this.ownerId !== userId) {
        this.$reset()
        this.ownerId = userId
      }
      this.loading = true
      try {
        const result = await apiRequest<GenerationPreferences>('/generation-preferences')
        if (this.ownerId === userId) this.selections = result
      } finally {
        if (this.ownerId === userId) this.loading = false
      }
    },
    async loadChannels(model: string) {
      const owner = this.ownerId
      const key = `${owner}:${model}`
      const pending = channelRequests.get(key)
      if (pending) return pending
      const request = (async () => {
        const result = await apiRequest<{ channels: GenerationChannel[] }>(
          `/model-options/${encodeURIComponent(model)}/channels`,
        )
        if (this.ownerId !== owner) return
        this.channels[model] = result.channels
          .filter((channel) => channel.available)
          .sort((a, b) => a.priority - b.priority)
      })()
      channelRequests.set(key, request)
      try {
        await request
      } finally {
        if (channelRequests.get(key) === request) channelRequests.delete(key)
      }
    },
    async save(modality: GenerationModality, selection: GenerationSelection) {
      const owner = this.ownerId
      this.saving = true
      try {
        const result = await apiRequest<GenerationPreferences>(
          `/generation-preferences/${modality}`,
          { method: 'PUT', body: JSON.stringify(selection) },
        )
        if (this.ownerId === owner) this.selections = result
      } finally {
        if (this.ownerId === owner) this.saving = false
      }
    },
  },
})
