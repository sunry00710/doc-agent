import { useEffect, useState } from 'react'
import { api, type Citation, type Job, type User } from '../api/client'
import { AgentWorkspace } from '../features/agent/AgentWorkspace'
import { LoginView } from '../features/auth/LoginView'
import { CitationPanel } from '../features/citations/CitationPanel'
import { JobStatus } from '../features/jobs/JobStatus'

export function App() {
  const [token, setToken] = useState(() => sessionStorage.getItem('doc-agent-token') ?? '')
  const [user, setUser] = useState<User | null>(null)
  const [citations, setCitations] = useState<Citation[]>([])
  const [jobs, setJobs] = useState<Job[]>([])

  useEffect(() => {
    if (!token) return
    void api.me(token).then(setUser).catch(() => { sessionStorage.removeItem('doc-agent-token'); setToken('') })
    void api.jobs(token).then((result) => setJobs(result.items)).catch(() => setJobs([]))
  }, [token])

  async function login(username: string, password: string) {
    const accessToken = await api.login(username, password)
    sessionStorage.setItem('doc-agent-token', accessToken)
    setToken(accessToken)
  }

  if (!token || !user) return <LoginView onLogin={login} />

  return <div className="app-shell">
    <nav className="side-nav" aria-label="Primary navigation"><div className="brand">Doc Agent</div><a className="active" href="#workspace">Workspace</a><a href="#documents">Documents</a><a href="#knowledge">Knowledge</a><a href="#reviews">Reviews</a><div className="account"><strong>{user.username}</strong><span>{user.role}</span><button type="button" onClick={() => { sessionStorage.removeItem('doc-agent-token'); setToken(''); setUser(null) }}>Sign out</button></div></nav>
    <AgentWorkspace onSend={(text, options) => api.chat(token, { text, confirmed: options.confirmed, idempotency_key: options.idempotencyKey })} onCitations={setCitations} />
    <div className="right-rail"><CitationPanel citations={citations} /><JobStatus jobs={jobs} onRetry={async (jobId) => { const next = await api.retryJob(token, jobId); setJobs((current) => current.map((job) => job.id === next.id ? next : job)) }} /></div>
  </div>
}
