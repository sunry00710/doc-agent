import { configDefaults, defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    // e2e/ 下是 Playwright 用例，不属于 vitest。排除规则放在这里而不是命令行：
    // `vitest --exclude e2e/**` 在 bash 下会被 shell 先展开成文件名列表，
    // vitest 会把多出来的位置参数当成过滤条件，于是反过来去跑 e2e（CI 上就是这么挂的）。
    exclude: [...configDefaults.exclude, '**/e2e/**'],
  },
})
