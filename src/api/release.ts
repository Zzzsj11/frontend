import { apiRequest } from './client'

export interface ReleaseInfo {
  version: string | null
  deployedAt: string | null
}

export const getReleaseInfo = (signal?: AbortSignal) =>
  apiRequest<ReleaseInfo>(`/release?_=${Date.now()}`, {
    headers: { 'X-Polling': '1' },
    signal,
  })
