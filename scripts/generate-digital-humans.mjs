/**
 * 批量调用英和异步生图 API，为资产库全部数字人生成真实形象，
 * 下载保存到 public/digital-humans/<id>.png（本地化存储）。
 * 运行：node scripts/generate-digital-humans.mjs
 */
import { mkdir, writeFile } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const BASE = 'https://api-aigc.fzyinghe.com'
const API_KEY = 'yh-tc6lxzhy3hjnzrj59qr4d8y213fvyixwv61t9tcq0dsbsot'
const OUT_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../public/digital-humans')

// 与 src/mock/data.ts 中的数字人一一对应
const humans = [
  { id: 'dh-luoli', name: '洛璃', style: '国风', description: '汉服古典美人，适合国风、古典意境场景' },
  { id: 'dh-xiner', name: '芯儿', style: '赛博朋克', description: '未来感机能少女，适合夜景霓虹、科幻场景' },
  { id: 'dh-hoshino', name: '星野', style: '二次元', description: '动漫风元气少年，适合校园、热血场景' },
  { id: 'dh-suwan', name: '苏晚', style: '写实', description: '真实系文艺女生，适合都市生活、情感叙事场景' },
  { id: 'dh-mia', name: '米娅', style: '虚拟偶像', description: '舞台系虚拟偶像，适合演出、打歌舞台场景' },
  { id: 'dh-ahao', name: '阿豪', style: '街头潮流', description: '嘻哈潮男，适合街舞、涂鸦街区场景' },
  { id: 'dh-manlu', name: '曼露', style: '复古港风', description: '90年代港风女郎，适合怀旧、霓虹夜色场景' },
  { id: 'dh-linxiao', name: '林霄', style: '商务', description: '干练商务精英，适合都市职场、纪实场景' },
  { id: 'dh-noona', name: '누나', style: '韩系青春', description: '24岁温柔文艺年上女性，黑长直中分披肩，米白针织开衫浅色长裙' },
  { id: 'dh-sonyeon', name: '少年', style: '韩系青春', description: '18岁清瘦敏感少年，深棕短发微乱，白衬衫深色外套' },
]

// 与 src/stores/project.ts generateDigitalHuman 保持一致的提示词模板
const buildPrompt = (description, style) =>
  `数字人角色定妆照：${description}。风格：${style}。竖版 3:4 半身人像，单人出镜，人物居中，五官清晰，干净纯色背景，摄影棚柔光，高质量细节，不要文字水印`

async function request(pathname, init) {
  const res = await fetch(`${BASE}${pathname}`, {
    ...init,
    headers: { 'x-api-key': API_KEY, 'Content-Type': 'application/json', Accept: '*/*' },
  })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  const body = await res.json()
  if (body.code !== 200) throw new Error(body.msg || `code=${body.code}`)
  return body.data
}

async function createTask(prompt) {
  const data = await request('/image/generation/tasks', {
    method: 'POST',
    body: JSON.stringify({ model: 'gpt-image-2', prompt, size: '768x1024', quality: 'medium', n: 1 }),
  })
  return data.taskId
}

async function waitForImage(taskId, label) {
  const deadline = Date.now() + 10 * 60 * 1000
  for (;;) {
    const task = await request(`/image/generation/tasks/${taskId}`)
    const status = String(task.status ?? '').toUpperCase()
    if (status === 'SUCCESS') {
      const url = task.resultUrl ?? task.resultUrls?.[0]
      if (!url) throw new Error('任务成功但无图片地址')
      return url
    }
    if (status.includes('FAIL')) throw new Error(task.failReason || '生成失败')
    if (Date.now() > deadline) throw new Error('轮询超时')
    console.log(`[${label}] ${status} progress=${task.progress ?? '-'}`)
    await new Promise((r) => setTimeout(r, 5000))
  }
}

async function download(url, file) {
  const res = await fetch(url)
  if (!res.ok) throw new Error(`下载失败 HTTP ${res.status}`)
  await writeFile(file, Buffer.from(await res.arrayBuffer()))
}

async function generateOne(h) {
  const prompt = buildPrompt(h.description, h.style)
  const taskId = await createTask(prompt)
  console.log(`[${h.name}] 任务已提交 ${taskId}`)
  const url = await waitForImage(taskId, h.name)
  const file = path.join(OUT_DIR, `${h.id}.png`)
  await download(url, file)
  console.log(`[${h.name}] ✅ 已保存 ${file}`)
  return { id: h.id, ok: true }
}

await mkdir(OUT_DIR, { recursive: true })
// 支持只重跑指定 id：node scripts/generate-digital-humans.mjs dh-sonyeon
const only = process.argv[2]
const targets = only ? humans.filter((h) => h.id === only) : humans
const results = await Promise.allSettled(targets.map((h) => generateOne(h)))
let failed = 0
results.forEach((r, i) => {
  if (r.status === 'rejected') {
    failed++
    console.error(`[${targets[i].name}] ❌ 失败：${r.reason?.message ?? r.reason}`)
  }
})
console.log(`\n完成：成功 ${results.length - failed}/${results.length}`)
process.exit(failed ? 1 : 0)
