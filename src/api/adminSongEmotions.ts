import { apiRequest } from './client'

export interface SongEmotionProfile {
  songCode: string
  songName: string
  artists: string
  lyrics: string
  primaryCategory: string | null
  secondaryCategory: string | null
  tertiaryCategory: string | null
  materialCategory: string
  seasons: string
  atmosphere: string
  characterSetting: string
  status: number
  createdAt: string
  updatedAt: string
}

export type SongEmotionInput = Omit<SongEmotionProfile, 'createdAt' | 'updatedAt'>

const bodyOf = (input: SongEmotionInput, includeCode: boolean) => ({
  ...(includeCode ? { song_code: input.songCode } : {}),
  song_name: input.songName,
  artists: input.artists,
  lyrics: input.lyrics,
  primary_category: input.primaryCategory,
  secondary_category: input.secondaryCategory,
  tertiary_category: input.tertiaryCategory,
  material_category: input.materialCategory,
  seasons: input.seasons,
  atmosphere: input.atmosphere,
  character_setting: input.characterSetting,
  status: input.status,
})

export const listSongEmotions = (query: URLSearchParams) =>
  apiRequest<{ total: number; items: SongEmotionProfile[] }>(
    `/admin/song-emotion-profiles?${query.toString()}`,
  )

export const createSongEmotion = (input: SongEmotionInput) =>
  apiRequest<SongEmotionProfile>('/admin/song-emotion-profiles', {
    method: 'POST',
    body: JSON.stringify(bodyOf(input, true)),
  })

export const updateSongEmotion = (input: SongEmotionInput) =>
  apiRequest<SongEmotionProfile>(
    `/admin/song-emotion-profiles/${encodeURIComponent(input.songCode)}`,
    { method: 'PATCH', body: JSON.stringify(bodyOf(input, false)) },
  )

export const deleteSongEmotion = (songCode: string) =>
  apiRequest<{ ok: boolean }>(`/admin/song-emotion-profiles/${encodeURIComponent(songCode)}`, {
    method: 'DELETE',
  })

export const importSongEmotions = (file: File) => {
  const body = new FormData()
  body.append('file', file)
  return apiRequest<{ ok: boolean; imported: number }>('/admin/song-emotion-profiles/import-xlsx', {
    method: 'POST',
    body,
  })
}
