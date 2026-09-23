// vendor 是目录中的模型品牌；这里归一到研发公司，不与接入渠道混淆。
export function modelCompany(model: { id: string; capabilities: Record<string, unknown> }): string {
  const explicit = model.capabilities.company
  if (typeof explicit === 'string' && explicit.trim()) return explicit.trim()
  const vendor = String(model.capabilities.vendor || '')
  const identity = `${vendor} ${model.id}`.toLowerCase()
  if (/claude|anthropic/.test(identity)) return 'Anthropic'
  if (/gpt|openai|o[134]-/.test(identity)) return 'OpenAI'
  if (/gemini|veo|imagen|google/.test(identity)) return 'Google'
  if (/seedance|seedream|doubao|字节/.test(identity)) return '字节跳动'
  if (/\bwan\b|qwen|通义|阿里/.test(identity)) return '阿里巴巴'
  if (/minimax|hailuo/.test(identity)) return 'MiniMax'
  if (/kling|可灵/.test(identity)) return '快手'
  if (/deepseek/.test(identity)) return 'DeepSeek'
  return vendor || '其他公司'
}
export function modelCategory(kind: string): string {
  if (['chat', 'text', 'llm'].includes(kind)) return 'text'
  return ['image', 'video'].includes(kind) ? kind : 'other'
}
