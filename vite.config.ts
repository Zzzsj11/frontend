import { defineConfig, type Plugin, type ViteDevServer } from 'vite'
import vue from '@vitejs/plugin-vue'
import { mkdir, writeFile } from 'node:fs/promises'
import path from 'node:path'

/** 本地化存储插件：接收远程图片地址，由 dev server 下载保存到 public/digital-humans/，
 *  返回本地路径。解决生图接口结果 URL 带签名 24 小时过期的问题。 */
const localImageStore = (): Plugin => ({
  name: 'local-image-store',
  configureServer(server: ViteDevServer) {
    server.middlewares.use('/local-store/digital-human', (req, res) => {
      if (req.method !== 'POST') {
        res.statusCode = 405
        res.end('Method Not Allowed')
        return
      }
      let raw = ''
      req.on('data', (chunk) => (raw += chunk))
      req.on('end', async () => {
        try {
          const { id, url } = JSON.parse(raw) as { id: string; url: string }
          if (!id || !url || !/^https?:/.test(url)) throw new Error('参数不合法')
          const safeId = id.replace(/[^\w-]/g, '')
          const dir = path.resolve(import.meta.dirname, 'public/digital-humans')
          await mkdir(dir, { recursive: true })
          const filename = `${safeId}-${Date.now()}.png`
          const download = await fetch(url)
          if (!download.ok) throw new Error(`下载图片失败（HTTP ${download.status}）`)
          await writeFile(path.join(dir, filename), Buffer.from(await download.arrayBuffer()))
          res.setHeader('Content-Type', 'application/json')
          res.end(JSON.stringify({ code: 200, path: `/digital-humans/${filename}` }))
        } catch (err) {
          res.statusCode = 500
          res.setHeader('Content-Type', 'application/json')
          res.end(JSON.stringify({ code: 500, msg: (err as Error).message }))
        }
      })
    })
  },
})

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue(), localImageStore()],
  server: {
    proxy: {
      // 真实异步生图接口（数字人形象生成）：开发环境经代理转发，规避浏览器跨域限制
      '/aigc': {
        target: 'https://api-aigc.fzyinghe.com',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/aigc/, ''),
      },
    },
  },
})
