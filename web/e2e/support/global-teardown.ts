import { execFileSync } from 'node:child_process'
import { rm } from 'node:fs/promises'

export default async function globalTeardown() {
  const runtime = process.env.DOC_AGENT_ISOLATED_E2E
  if (!runtime) return
  const { pids, runRoot } = JSON.parse(runtime) as {
    pids: number[]
    runRoot: string
  }
  for (const pid of pids) {
    if (!pid) continue
    try {
      if (process.platform === 'win32') {
        execFileSync('taskkill', ['/PID', String(pid), '/T', '/F'], {
          stdio: 'ignore',
        })
      } else {
        process.kill(-pid, 'SIGTERM')
      }
    } catch {
      // The owned process tree already exited.
    }
  }
  if (runRoot) await rm(runRoot, { recursive: true, force: true })
}
