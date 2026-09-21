const STORAGE_KEY = 'mv-agent-test-run'
const VALID_RUN_ID = /^[a-zA-Z0-9][a-zA-Z0-9._-]{0,159}$/

/** 显式测试链接仅标记当前页签，避免浏览器验收被记为普通业务流量。 */
export function agentTestHeaders(): Record<string, string> {
  const params = new URLSearchParams(window.location.search)
  const requested = params.get('agent_test_run_id')
  let runId = ''
  try {
    if (requested === 'off') sessionStorage.removeItem(STORAGE_KEY)
    else if (requested && VALID_RUN_ID.test(requested))
      sessionStorage.setItem(STORAGE_KEY, requested)
    runId = sessionStorage.getItem(STORAGE_KEY) || ''
  } catch {
    // 禁用存储时仍允许当前链接携带归因，但不跨导航延续。
    runId = requested || ''
  }
  if (requested === 'off' || !VALID_RUN_ID.test(runId)) return {}
  return {
    'X-Agent-Name': 'code-agent',
    'X-Agent-Run-Id': runId,
    'X-Test-Run-Id': runId,
  }
}
