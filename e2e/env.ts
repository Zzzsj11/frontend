/**
 * e2e 远程测试的凭据与批次约定（所有远程 spec 统一从这里取，禁止各自硬编码回退）。
 *
 * fail-fast 规则：目标 baseURL 非 localhost 时，必须显式提供 REMOTE_E2E_PASSWORD
 * （环境变量或 e2e/.env，由 playwright.config.ts 加载）。曾经因为静默回退到本地开发
 * 密码 123456，打远程时直到 login 401 才发现整轮验收白跑，故此处直接拒绝启动。
 * 仅本地目标（preflight 起的服务）允许使用开发默认密码。
 */
const LOCAL_HOSTNAMES = new Set(['127.0.0.1', 'localhost', '[::1]'])

export function targetBaseURL(): string {
  return (
    process.env.REMOTE_API_BASE_URL ||
    process.env.PLAYWRIGHT_BASE_URL ||
    'http://124.222.219.76:5173'
  )
}

function isLocalTarget(url: string): boolean {
  try {
    return LOCAL_HOSTNAMES.has(new URL(url).hostname)
  } catch {
    return false
  }
}

export function remoteCredentials(): { username: string; password: string } {
  const username = process.env.REMOTE_E2E_USERNAME || 'admin'
  const password = process.env.REMOTE_E2E_PASSWORD
  if (!password) {
    if (isLocalTarget(targetBaseURL())) return { username, password: '123456' }
    throw new Error(
      `[e2e] 目标 ${targetBaseURL()} 不是本地环境，必须显式设置 REMOTE_E2E_PASSWORD` +
        '（环境变量，或复制 e2e/.env.example 为 e2e/.env 后填写）；已拒绝使用本地开发默认密码。',
    )
  }
  return { username, password }
}

/** 测试批次 ID：一次运行内的产物目录、项目命名与 X-Test-Run-Id 请求头共用同一值。 */
export function testRunId(prefix = 'e2e'): string {
  return (
    process.env.REMOTE_E2E_RUN_ID ||
    process.env.REAL_E2E_RUN_ID ||
    `${prefix}-${new Date().toISOString().replaceAll(/[:.]/g, '-')}`
  )
}
