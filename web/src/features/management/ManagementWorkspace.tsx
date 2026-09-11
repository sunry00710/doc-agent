import { useEffect, useState, type FormEvent } from 'react'
import { RefreshCw } from 'lucide-react'
import { api, type ApiError, type Job, type ProjectMember } from '../../api/client'
import { displayError, displayLabel, zhCN } from '../../app/strings'

const membershipLabels = { contributor: '作者', reviewer: '项目评审员', owner: '项目负责人' }

export function ManagementWorkspace({ token, projectId }: { token: string; projectId: string }) {
  const [tab, setTab] = useState('members')
  const [members, setMembers] = useState<ProjectMember[]>([])
  const [jobs, setJobs] = useState<Job[]>([])
  const [userId, setUserId] = useState('')
  const [membershipRole, setMembershipRole] = useState<ProjectMember['membership_role']>('contributor')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [revision, setRevision] = useState(0)
  useEffect(() => {
    let active = true
    setLoading(true)
    setError('')
    void Promise.all([projectId ? api.projectMembers(token, projectId) : Promise.resolve([]), api.jobs(token)]).then(([nextMembers, nextJobs]) => {
      if (active) { setMembers(nextMembers); setJobs(nextJobs.items) }
    }).catch(() => { if (active) setError('管理数据加载失败。') }).finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [token, projectId, revision])

  async function addMember(event: FormEvent) {
    event.preventDefault()
    if (!projectId || !userId.trim() || busy) return
    setBusy(true)
    setError('')
    try { await api.addProjectMember(token, projectId, userId.trim(), membershipRole); setUserId(''); setRevision((value) => value + 1) }
    catch (reason) { setError(displayError((reason as Partial<ApiError>).code, '成员添加失败，请检查用户 ID 和现有成员列表。')) }
    finally { setBusy(false) }
  }

  async function retry(job: Job) {
    if (busy) return
    setBusy(true)
    setError('')
    try { await api.retryJob(token, job.id); setRevision((value) => value + 1) }
    catch (reason) { setError(displayError((reason as Partial<ApiError>).code, '任务重试失败。')) }
    finally { setBusy(false) }
  }

  return <main className="management-workspace">
    <header className="review-task-header"><h1>管理</h1><button type="button" className="icon-button" title="刷新管理数据" aria-label="刷新管理数据" disabled={loading || busy} onClick={() => setRevision((value) => value + 1)}><RefreshCw size={16} /></button></header>
    <div className="hub-tabs" role="tablist" aria-label="管理视图"><button role="tab" aria-selected={tab === 'members'} className={tab === 'members' ? 'selected' : ''} onClick={() => setTab('members')}>项目成员</button><button role="tab" aria-selected={tab === 'jobs'} className={tab === 'jobs' ? 'selected' : ''} onClick={() => setTab('jobs')}>我的后台任务</button></div>
    {loading && <p role="status">正在加载…</p>}
    {error && <p role="alert" className="error">{error}</p>}
    {!loading && tab === 'members' && <section>
      <h2>当前项目成员</h2>
      {!projectId ? <p>尚未选择项目。</p> : <>
        <div className="table-scroll"><table><thead><tr><th>用户 ID</th><th>项目权限</th></tr></thead><tbody>{members.map((member) => <tr key={member.user_id}><td>{member.user_id}</td><td>{membershipLabels[member.membership_role]}</td></tr>)}</tbody></table></div>
        <form className="member-form" onSubmit={addMember}><label>现有用户 ID<input value={userId} onChange={(event) => setUserId(event.target.value)} required /></label><label>项目权限<select value={membershipRole} onChange={(event) => setMembershipRole(event.target.value as ProjectMember['membership_role'])}>{Object.entries(membershipLabels).map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></label><button type="submit" disabled={busy || !userId.trim()}>添加成员</button></form>
      </>}
    </section>}
    {!loading && tab === 'jobs' && <section><h2>我的后台任务</h2>{jobs.length === 0 && <p className="muted">暂无后台任务。</p>}{jobs.map((job) => <article className="promotion-row" key={job.id}><strong>{job.job_type}</strong><span>{displayLabel(zhCN.status, job.status)} · {job.updated_at}</span>{job.error && <p className="error">{job.error.message}</p>}{job.status === 'failed' && <button type="button" disabled={busy} onClick={() => void retry(job)}>重试任务</button>}</article>)}</section>}
  </main>
}
