import { useState } from 'react'
import type { FormEvent } from 'react'

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
      setError(reason instanceof Error ? reason.message : 'Sign-in failed.')
    } finally {
      setSubmitting(false)
    }
  }

  return <main className="login-shell">
    <form className="login-card" onSubmit={submit}>
      <p className="eyebrow">Doc Agent</p>
      <h1>Document quality workspace</h1>
      <p className="muted">Sign in to work with your authorized projects and knowledge.</p>
      <label>Username<input autoComplete="username" value={username} onChange={(event) => setUsername(event.target.value)} required /></label>
      <label>Password<input autoComplete="current-password" type="password" value={password} onChange={(event) => setPassword(event.target.value)} required /></label>
      {error && <p className="error" role="alert">{error}</p>}
      <button disabled={submitting} type="submit">{submitting ? 'Signing in…' : 'Sign in'}</button>
    </form>
  </main>
}
