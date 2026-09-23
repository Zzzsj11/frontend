let token = ''
export function setToken(value: string) {
  token = value
}
export async function api<T>(path: string, method = 'GET', body?: unknown): Promise<T> {
  const response = await fetch('/portal' + path, {
    method,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  }).catch(() => {
    throw new Error('网络连接失败，请稍后重试')
  })
  if (!response.ok) {
    const data = await response.json().catch(() => ({}))
    const messages: Record<number, string> = {
      401: path === '/login' ? '邮箱或密码不正确' : '登录已失效，请重新登录',
      403: '当前账号无权执行此操作',
      404: '请求的内容不存在',
      409: '操作冲突，请刷新后重试',
      422: '请检查输入格式和数值范围',
      429: '尝试次数过多，请稍后重试',
    }
    throw new Error(
      typeof data.detail === 'string' && /[\u4e00-\u9fff]/.test(data.detail)
        ? data.detail
        : messages[response.status] || '服务暂时不可用，请稍后重试',
    )
  }
  return response.status === 204 ? (undefined as T) : response.json()
}
