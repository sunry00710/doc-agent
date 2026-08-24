import { useState } from 'react'
import type { FormEvent } from 'react'
import { displayError } from '../../app/strings'
import type { ApiError } from '../../api/client'

type LoginViewProps = {
  onLogin: (username: string, password: string) => Promise<void>
}

export function LoginView({ onLogin }: LoginViewProps) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError('')
    setSubmitting(true)
    try {
      await onLogin(username, password)
    } catch (reason) {
      const apiError = reason as Partial<ApiError>
      setError(displayError(apiError.code, '登录失败，请检查用户名和密码。'))
    } finally {
      setSubmitting(false)
    }
  }

  return <main className="login-shell">
    <form className="login-card" onSubmit={submit}>
      <p className="eyebrow">Doc Agent</p>
      <h1>文档质量工作台</h1>
      <p className="muted">登录后访问你有权限的项目、文档和知识库。</p>
      <label>用户名<input autoComplete="username" value={username} onChange={(event) => setUsername(event.target.value)} required /></label>
      <label>密码<input autoComplete="current-password" type="password" value={password} onChange={(event) => setPassword(event.target.value)} required /></label>
      {error && <p className="error" role="alert">{error}</p>}
      <button disabled={submitting} type="submit">{submitting ? '登录中…' : '登录'}</button>
    </form>
  </main>
}
