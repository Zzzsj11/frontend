import { apiRequest } from './client'
const cleanName = (name: string) => name.replace(/[\\/:*?"<>|]/g, '_')
const imageExtension = (src: string) =>
  new URL(src, location.href).pathname.match(/\.(png|jpe?g|webp|gif|avif)$/i)?.[1] || 'png'

/** TOS 通过短期签名链接直接下载，避免跨域 Fetch 依赖存储桶 CORS。 */
export async function downloadImage(src: string, name: string) {
  const source = new URL(src, location.href)
  if (source.protocol === 'https:') {
    try {
      const result = await apiRequest<{ url: string }>(
        `/media/image-download?${new URLSearchParams({ src, name })}`,
        {},
        true,
        [403, 422, 503],
      )
      if (!result.url) throw new Error('下载地址不可用')
      const anchor = document.createElement('a')
      anchor.href = result.url
      anchor.download = `${cleanName(name)}.${imageExtension(src)}`
      anchor.click()
      return
    } catch {
      /* 非平台图片可继续尝试公开地址。 */
    }
  }
  // 本地/其他公开图片不携带业务鉴权头；使用 Blob 保留原始编码下载。
  const response = await fetch(src)
  if (!response.ok) throw new Error('下载失败')
  const blob = await response.blob()
  const extensions: Record<string, string> = {
    'image/png': 'png',
    'image/jpeg': 'jpg',
    'image/webp': 'webp',
    'image/gif': 'gif',
    'image/svg+xml': 'svg',
    'image/avif': 'avif',
  }
  const extension = extensions[blob.type.split(';')[0] || ''] || imageExtension(src)
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `${cleanName(name)}.${extension}`
  anchor.click()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}
