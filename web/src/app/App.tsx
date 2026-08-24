import { useEffect, useState } from 'react'
import { displayLabel, zhCN } from './strings'
import {
  api,
  type Citation,
  type Document,
  type DocumentVersion,
  type Job,
  type ReviewDetail,
  type User,
} from '../api/client'
import { AgentWorkspace } from '../features/agent/AgentWorkspace'
import type { AgentContext } from '../features/agent/AgentWorkspace'
import { LoginView } from '../features/auth/LoginView'
import { CitationPanel } from '../features/citations/CitationPanel'
import { DocumentHub } from '../features/documents/DocumentHub'
import { NewDocumentForm } from '../features/documents/NewDocumentForm'
import { KnowledgeManager } from '../features/knowledge/KnowledgeManager'
import { JobStatus } from '../features/jobs/JobStatus'

const navigation = [
  ['workspace', '工作台'],
  ['documents', '文档'],
  ['knowledge', '知识库'],
  ['reviews', '评审'],
] as const

export function App() {
  const [token, setToken] = useState(() => sessionStorage.getItem('doc-agent-token') ?? '')
  const [user, setUser] = useState<User | null>(null)
  const [view, setView] = useState(() => window.location.hash.slice(1) || 'workspace')
  const [projectId, setProjectId] = useState('')
  const [projects, setProjects] = useState<{ id: string; name: string }[]>([])
  const [documents, setDocuments] = useState<Document[]>([])
  const [document, setDocument] = useState<Document | null>(null)
  const [versions, setVersions] = useState<DocumentVersion[]>([])
  const [selectedVersion, setSelectedVersion] = useState<DocumentVersion | null>(null)
  const [source, setSource] = useState('')
  const [review, setReview] = useState<ReviewDetail | null>(null)
  const [citations, setCitations] = useState<Citation[]>([])
  const [jobs, setJobs] = useState<Job[]>([])
  // 右栏（引用与任务）可折叠：阅读长文档时自动收起，腾出整幅版面
  const [railOpen, setRailOpen] = useState(true)

  useEffect(() => {
    // 仅工作台需要常驻引用面板；进入文档/评审等阅读视图自动收起
    setRailOpen(view === 'workspace')
  }, [view])

  useEffect(() => {
    if (!token) return
    void api.me(token).then(setUser).catch(() => {
      sessionStorage.removeItem('doc-agent-token')
      setToken('')
    })
    void api.jobs(token).then((result) => setJobs(result.items))
    void api.projects(token).then((result) => {
      setProjects(result)
      if (result[0]) setProjectId(result[0].id)
    })
  }, [token])

  useEffect(() => {
    if (!token || !projectId) return
    void api.documents(token, projectId).then(setDocuments)
  }, [projectId, token])

  useEffect(() => {
    if (!token || !document) return
    void api.versions(token, document.id).then(setVersions)
  }, [document, token])

  useEffect(() => {
    if (!token || !document) return
    void api.reviews(token, document.id).then(async (items) => {
      const matched = selectedVersion
        ? items.find((item) => item.version_id === selectedVersion.id)
        : items[0]
      setReview(matched ? await api.review(token, matched.id) : null)
    })
  }, [document, selectedVersion, token])

  async function selectVersion(version: DocumentVersion) {
    setSelectedVersion(version)
    setSource(await api.versionContent(token, version.document_id, version.number))
  }

  function selectDocument(next: Document) {
    setDocument(next)
    setSelectedVersion(null)
    setSource('')
  }

  async function login(username: string, password: string) {
    const accessToken = await api.login(username, password)
    sessionStorage.setItem('doc-agent-token', accessToken)
    setToken(accessToken)
  }

  function navigate(next: string) {
    window.location.hash = next
    setView(next)
  }

  if (!token || !user) return <LoginView onLogin={login} />

  const refreshReview = async () => { if (review) setReview(await api.review(token, review.id)) }

  const createReview = async () => {
    if (!document || !selectedVersion) return
    const created = await api.createReview(token, document.id, selectedVersion.id)
    setReview(await api.review(token, created.id))
  }

  const currentProject = projects.find((item) => item.id === projectId)
  const versionLabel = document && selectedVersion ? `《${document.title}》v${selectedVersion.number}` : undefined
  const agentContext: AgentContext | undefined = currentProject
    ? { projectName: currentProject.name, documentTitle: document?.title ?? null, versionLabel: selectedVersion ? `v${selectedVersion.number}` : null }
    : undefined
  // 选中版本时以文档所属项目为准，避免与侧栏项目选择不一致导致后端校验失败
  const chatProjectId = document && selectedVersion ? document.project_id : projectId || undefined

  return <div className={railOpen ? 'app-shell' : 'app-shell rail-closed'}>
    <nav className="side-nav" aria-label="主导航">
      <div className="brand">Doc Agent</div>
      {navigation.map(([id, label]) => <button type="button" className={view === id ? 'active' : ''} key={id} onClick={() => navigate(id)}>{label}</button>)}
      <label className="project-select">项目
        <select value={projectId} onChange={(event) => setProjectId(event.target.value)}>
          <option value="">请选择项目</option>
          {projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}
        </select>
      </label>
      <div className="account">
        <strong>{user.username}</strong>
        <span>{displayLabel(zhCN.role, user.role)}</span>
        <button type="button" onClick={() => { sessionStorage.removeItem('doc-agent-token'); setToken(''); setUser(null) }}>退出登录</button>
      </div>
    </nav>
    {view === 'workspace' && <AgentWorkspace context={agentContext} onSend={(text, options) => api.chat(token, { text, confirmed: options.confirmed, idempotency_key: options.idempotencyKey, project_id: chatProjectId, document_version_id: selectedVersion?.id })} onCitations={setCitations} />}
    {view === 'knowledge' && <KnowledgeManager token={token} role={user.role} currentUserId={user.id} selectedVersionId={selectedVersion?.id} selectedVersionLabel={versionLabel} />}
    {(view === 'documents' || view === 'reviews') && <div className="content-columns">
      <aside className="document-list">
        <h2>文档</h2>
        {documents.length === 0 && <p className="muted">当前项目还没有文档。</p>}
        {documents.map((item) => <button type="button" className={item.id === document?.id ? 'selected' : ''} key={item.id} onClick={() => { selectDocument(item); navigate(view) }}>{item.title}</button>)}
        {projectId && <NewDocumentForm token={token} projectId={projectId} onCreated={(created) => { setDocuments((current) => [...current, created]); selectDocument(created) }} />}
      </aside>
      <DocumentHub token={token} document={document} versions={versions} source={source} selectedVersion={selectedVersion} onSelectVersion={(version) => void selectVersion(version)} onVersionUploaded={(version) => { setVersions((current) => current.some((item) => item.id === version.id) ? current : [...current, version]); void selectVersion(version) }} review={review} onRefreshReview={refreshReview} onCreateReview={createReview} role={user.role} currentUserId={user.id} />
    </div>}
    {railOpen
      ? <div className="right-rail">
          <button type="button" className="rail-collapse" onClick={() => setRailOpen(false)}>收起面板 ›</button>
          <CitationPanel citations={citations} />
          <JobStatus jobs={jobs} onRetry={async (jobId) => { const next = await api.retryJob(token, jobId); setJobs((current) => current.map((job) => job.id === next.id ? next : job)) }} />
        </div>
      : <button type="button" className="rail-toggle" onClick={() => setRailOpen(true)}>引用与任务</button>}
  </div>
}
