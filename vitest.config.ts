import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  test: {
    include: ['tests/**/*.test.ts'],
    environment: 'jsdom',
    // 控制组件库 DOM 测试并行度，避免多进程争用导致虚假的交互超时。
    maxWorkers: 4,
    setupFiles: ['./tests/setup.ts'],
    restoreMocks: true,
  },
})
