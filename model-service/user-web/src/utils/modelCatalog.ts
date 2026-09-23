// 按模型厂商分组；转发渠道不作为厂商品牌。
export function modelVendor(id: string): string {
  const name = id
    .toLowerCase()
    .replace(/^yseeai--/, '')
    .replace(/^(svip-|s-|z-)/, '')
  if (/^(qwen|wan)/.test(name)) return 'Alibaba（阿里云）'
  if (name.startsWith('claude')) return 'Anthropic'
  if (/^(doubao|seedance|dreamina|dreamactor|seedream|dola)/.test(name))
    return 'ByteDance（字节跳动）'
  if (name.startsWith('deepseek')) return 'DeepSeek'
  if (/^(gemini|veo)/.test(name)) return 'Google'
  if (name.startsWith('kling')) return 'Kuaishou（快手）'
  if (/^(minimax|h3-)/.test(name)) return 'MiniMax'
  if (name.startsWith('kimi')) return 'Moonshot（月之暗面）'
  if (/^(gpt-|codex-)/.test(name)) return 'OpenAI'
  if (name.startsWith('grok')) return 'xAI'
  if (name.startsWith('glm')) return 'Zhipu（智谱）'
  return '其他厂商'
}
export function alphabetical(a: string, b: string): number {
  return a.localeCompare(b, 'en', { sensitivity: 'base', numeric: true })
}
