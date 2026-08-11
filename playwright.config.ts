import { defineConfig, devices } from '@playwright/test'
import { config as loadEnv } from 'dotenv'
import { join } from 'node:path'
import { targetBaseURL } from './e2e/env'

// 远程 e2e 凭据从 e2e/.env 读取（已 gitignore，模板见 e2e/.env.example）
loadEnv({ path: join(process.cwd(), 'e2e', '.env'), quiet: true })

// 带远程开关（REMOTE_*/ADMIN_*）的 spec 意图就是打已部署环境：baseURL 默认取
// e2e/env.ts 的 targetBaseURL()（可用 PLAYWRIGHT_BASE_URL 覆盖），且不再本地起 dev server。
// 曾经 remote-frontend 未设 PLAYWRIGHT_BASE_URL 时静默打到本地 preview，整轮“远程验收”
// 实际没碰线上，login 404 才暴露。
const remoteRun = !!(
  process.env.REMOTE_FRONTEND_E2E ||
  process.env.REMOTE_API_E2E ||
  process.env.ADMIN_API_E2E ||
  process.env.ADMIN_CONSOLE_E2E
)

export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  reporter: 'list',
  use: {
    baseURL:
      process.env.PLAYWRIGHT_BASE_URL || (remoteRun ? targetBaseURL() : 'http://127.0.0.1:4173'),
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer:
    process.env.PLAYWRIGHT_BASE_URL || remoteRun
      ? undefined
      : {
          command: 'npm run dev -- --host 127.0.0.1 --port 4173',
          url: 'http://127.0.0.1:4173',
          reuseExistingServer: false,
        },
})
