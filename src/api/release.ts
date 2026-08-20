import { apiRequest } from './client'

export interface ReleaseInfo {
  version: string | null
  deployedAt: string | null
}

export const getReleaseInfo = () => apiRequest<ReleaseInfo>('/release')
