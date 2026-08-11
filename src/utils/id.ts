let idSeed = 0

/** 本地临时 ID（乐观更新占位，服务端保存后替换为真实 ID） */
export const nextId = (prefix = 'line') => `${prefix}-${Date.now()}-${idSeed++}`
