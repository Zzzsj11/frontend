import { defineConfig, devices } from '@playwright/test'
import { config as loadEnv } from 'dotenv'
import { join } from 'node:path'

// 远程 e2e 凭据从 e2e/.env 读取（已 gitignore，模板见 e2e/.env.example）
loadEnv({ path: join(process.cwd(), 'e2e', '.env'), quiet: true })

export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  reporter: 'list',
  use: {
    baseURL: process.env.PLAYWRIGHT_BASE_URL || 'http://127.0.0.1:4173',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: process.env.PLAYWRIGHT_BASE_URL
    ? undefined
    : {
        command: 'npm run dev -- --host 127.0.0.1 --port 4173',
        url: 'http://127.0.0.1:4173',
        reuseExistingServer: false,
      },
})
