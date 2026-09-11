import { execFileSync, spawn, spawnSync, type ChildProcess } from 'node:child_process'
import { createServer } from 'node:net'
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'

const root = resolve(import.meta.dirname, '../../..')
const web = resolve(root, 'web')
const children: ChildProcess[] = []

async function waitFor(url: string, ownedChildren: ChildProcess[] = []) {
  for (let attempt = 0; attempt < 60; attempt += 1) {
    for (const child of ownedChildren) {
      if (child.exitCode !== null || child.signalCode !== null) {
        throw new Error(`E2E server exited before becoming ready: ${url}`)
      }
    }
    try {
      const response = await fetch(url)
      if (response.ok) return
    } catch {
      // The owned test server is still starting.
    }
    await new Promise((resolveWait) => setTimeout(resolveWait, 250))
  }
  throw new Error(`E2E server did not become ready: ${url}`)
}

function requiredFixtureValue(fixture: Record<string, unknown>, key: string) {
  const value = fixture[key]
  if (typeof value !== 'string' || value.length === 0) {
    throw new Error(`E2E manifest is missing required field: ${key}`)
  }
  return value
}

async function allocatePort() {
  return new Promise<number>((resolvePort, reject) => {
    const server = createServer()
    server.once('error', reject)
    server.listen(0, '127.0.0.1', () => {
      const address = server.address()
      if (!address || typeof address === 'string') {
        server.close()
        reject(new Error('Unable to allocate E2E port'))
        return
      }
      const port = address.port
      server.close((error) => error ? reject(error) : resolvePort(port))
    })
  })
}

function start(command: string, args: string[], env: NodeJS.ProcessEnv) {
  const child = spawn(command, args, {
    cwd: root,
    env,
    stdio: 'inherit',
    detached: process.platform !== 'win32',
    shell: process.platform === 'win32' && command.endsWith('.cmd'),
  })
  children.push(child)
  return child
}

async function stopChildren() {
  for (const child of children) {
    if (!child.pid) continue
    try {
      if (process.platform === 'win32') {
        execFileSync('taskkill', ['/PID', String(child.pid), '/T', '/F'], {
          stdio: 'ignore',
        })
      } else {
        process.kill(-child.pid, 'SIGTERM')
      }
    } catch {
      // The owned process tree already exited.
    }
  }
}

export default async function globalSetup() {
  const runRoot = await mkdtemp(join(tmpdir(), 'doc-agent-e2e-'))
  const database = join(runRoot, 'e2e.db')
  const storage = join(runRoot, 'storage')
  const manifest = join(runRoot, 'manifest.json')
  const backendPort = await allocatePort()
  const frontendPort = await allocatePort()
  const uv = process.platform === 'win32' ? 'uv.exe' : 'uv'
  const npm = process.platform === 'win32' ? 'npm.cmd' : 'npm'

  try {
    const seed = spawnSync(
      uv,
      [
        'run', '--directory', root,
        'python', 'tests/e2e/seed_promotion_quality.py',
        '--database', database,
        '--storage', storage,
        '--manifest', manifest,
      ],
      { cwd: root, stdio: 'inherit', env: { ...process.env, PYTHONPATH: root } },
    )
    if (seed.status !== 0) throw new Error('Unable to seed isolated E2E data')

    const backend = start(
      uv,
      [
        'run', '--directory', root,
        'uvicorn', 'app.main:create_app', '--factory',
        '--host', '127.0.0.1', '--port', String(backendPort),
      ],
      {
        ...process.env,
        ENVIRONMENT: 'test',
        DATABASE_URL: `sqlite:///${database.replaceAll('\\', '/')}`,
        STORAGE_DIR: storage,
        MODEL_PROVIDER: 'fake',
        JWT_SECRET: 'e2e-disposable-secret-at-least-thirty-two-bytes',
        // E2E 只验证 UI 流程：关掉语义向量，避免依赖 fastembed 模型缓存
        // （默认落在系统临时目录，可能被清理，干净机器上会让 hybrid 检索直接 500）。
        // 注意：前端仍请求 mode=hybrid，后端在 embedding_enabled=false 时退回关键词检索。
        EMBEDDING_ENABLED: 'false',
      },
    )
    // 上传版本改为异步入队后，E2E 必须同时拉起 worker，否则索引任务永远停留在「排队中」
    const worker = start(
      uv,
      ['run', '--directory', root, 'python', 'run_worker.py'],
      {
        ...process.env,
        ENVIRONMENT: 'test',
        DATABASE_URL: `sqlite:///${database.replaceAll('\\', '/')}`,
        STORAGE_DIR: storage,
        MODEL_PROVIDER: 'fake',
        JWT_SECRET: 'e2e-disposable-secret-at-least-thirty-two-bytes',
        EMBEDDING_ENABLED: 'false',
      },
    )
    const frontend = start(
      npm,
      [
        '--prefix', web, 'run', 'dev', '--',
        '--host', '127.0.0.1', '--port', String(frontendPort),
      ],
      {
        ...process.env,
        DOC_AGENT_API_URL: `http://127.0.0.1:${backendPort}`,
      },
    )
    await waitFor(`http://127.0.0.1:${backendPort}/api/health`, [backend])
    await waitFor(`http://127.0.0.1:${frontendPort}`, [frontend])

    const fixture = JSON.parse(await readFile(manifest, 'utf-8')) as Record<string, unknown>
    for (const key of [
      'password', 'project', 'author', 'reviewer', 'admin',
      'mandatoryTitle', 'optionalTitle', 'unconfirmedTitle', 'optionalNeedle',
    ]) {
      requiredFixtureValue(fixture, key)
    }
    const runtime = JSON.stringify({
      ...fixture,
      baseURL: `http://127.0.0.1:${frontendPort}`,
      runRoot,
      pids: [backend.pid, frontend.pid, worker.pid],
    })
    process.env.DOC_AGENT_ISOLATED_E2E = runtime
    await writeFile(join(runRoot, 'runtime.json'), runtime)
  } catch (reason) {
    await stopChildren()
    await rm(runRoot, { recursive: true, force: true })
    throw reason
  }
}
