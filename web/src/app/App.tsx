import { useEffect, useMemo, useRef, useState } from 'react'
import { ArrowLeft } from 'lucide-react'
import { displayLabel, zhCN } from './strings'
import { canGovernKnowledge, isAdmin } from './roles'
import {
  api,
  type Citation,
  type Document,
  type DocumentVersion,
  type Job,
  type KnowledgeSpace,
  type User,
} from '../api/client'
import { AgentWorkspace } from '../features/agent/AgentWorkspace'
import type { AgentContext, KnowledgeSource } from '../features/agent/AgentWorkspace'
import { LoginView } from '../features/auth/LoginView'
import { CitationPanel } from '../features/citations/CitationPanel'
import { DocumentHub } from '../features/documents/DocumentHub'
import { NewDocumentForm } from '../features/documents/NewDocumentForm'
import { KnowledgeManager } from '../features/knowledge/KnowledgeManager'
import { KnowledgeGovernance } from '../features/knowledge/KnowledgeGovernance'
import { ManagementWorkspace } from '../features/management/ManagementWorkspace'
import { ReviewWorkspace } from '../features/reviews/ReviewWorkspace'
import { JobStatus } from '../features/jobs/JobStatus'

const navigation = [
  ['workspace', '工作台'],
  ['documents', '文档'],
  ['knowledge', '知识库'],
  ['reviews', '待我评审'],
] as const

const sessionKeys = {
  projectId: 'doc-agent-project-id',
  documentId: 'doc-agent-document-id',
  versionId: 'doc-agent-version-id',
}

export function App() {
  const [token, setToken] = useState(() => sessionStorage.getItem('doc-agent-token') ?? '')
  const [user, setUser] = useState<User | null>(null)
  const [view, setView] = useState(() => window.location.hash.slice(1) || 'workspace')
  const [projectId, setProjectId] = useState(() => sessionStorage.getItem(sessionKeys.projectId) ?? '')
  const [projects, setProjects] = useState<{ id: string; name: string }[]>([])
  const [documents, setDocuments] = useState<Document[]>([])
  const [document, setDocument] = useState<Document | null>(null)
  const [versions, setVersions] = useState<DocumentVersion[]>([])
  const [selectedVersion, setSelectedVersion] = useState<DocumentVersion | null>(null)
  const [source, setSource] = useState('')
  const [sourceVersionId, setSourceVersionId] = useState<string | null>(null)
  const [documentError, setDocumentError] = useState('')
  const [citations, setCitations] = useState<Citation[]>([])
  const [jobs, setJobs] = useState<Job[]>([])
  const [desiredVersionId, setDesiredVersionId] = useState<string | null>(() => sessionStorage.getItem(sessionKeys.versionId))
  const [versionLoadRequest, setVersionLoadRequest] = useState(0)
  const [knowledgeReturnDocumentId, setKnowledgeReturnDocumentId] = useState<string | null>(null)
  const [documentFilter, setDocumentFilter] = useState('')
  const [knowledgeSpaces, setKnowledgeSpaces] = useState<KnowledgeSpace[]>([])
  const [selectedSourceIds, setSelectedSourceIds] = useState<string[]>(() => {
    try { return JSON.parse(sessionStorage.getItem('doc-agent-source-ids') ?? '[]') as string[] } catch { return [] }
  })
  const bootstrapGeneration = useRef(0)
  const documentsGeneration = useRef(0)
  const versionsGeneration = useRef(0)
  const sourceGeneration = useRef(0)
  const sourceNavigationGeneration = useRef(0)
  const previousProjectId = useRef(projectId)
  const [railOpen, setRailOpen] = useState(true)
  const reviewDocuments = useMemo(() => documents.filter((item) => item.project_id === projectId), [documents, projectId])
  const filteredDocuments = useMemo(() => {
    const query = documentFilter.trim().toLowerCase()
    return query ? documents.filter((item) => item.title.toLowerCase().includes(query)) : documents
  }, [documents, documentFilter])
  // 切换项目时清空筛选，避免上一个项目的筛选词隐藏新项目全部文档
  useEffect(() => { setDocumentFilter('') }, [projectId])

  useEffect(() => {
    const onHashChange = () => setView(window.location.hash.slice(1) || 'workspace')
    window.addEventListener('hashchange', onHashChange)
    return () => window.removeEventListener('hashchange', onHashChange)
  }, [])

  // 任何 API 返回 401（token 过期）时，API client 会清 token 并广播；这里回到登录页
  useEffect(() => {
    const onAuthExpired = () => setToken('')
    window.addEventListener('doc-agent-auth-expired', onAuthExpired)
    return () => window.removeEventListener('doc-agent-auth-expired', onAuthExpired)
  }, [])

  useEffect(() => {
    // 仅工作台需要常驻引用面板；进入文档/评审等阅读视图自动收起
    setRailOpen(view === 'workspace')
  }, [view])

  useEffect(() => {
    if (!token) return
    const generation = ++bootstrapGeneration.current
    void api.me(token).then((nextUser) => {
      if (generation === bootstrapGeneration.current) setUser(nextUser)
    }).catch(() => {
      if (generation !== bootstrapGeneration.current) return
      sessionStorage.removeItem('doc-agent-token')
      setToken('')
    })
    void api.jobs(token).then((result) => {
      if (generation === bootstrapGeneration.current) setJobs(result.items)
    })
    void api.projects(token).then((result) => {
      if (generation !== bootstrapGeneration.current) return
      setProjects(result)
      setProjectId((current) => result.some((project) => project.id === current) ? current : (result[0]?.id ?? ''))
    })
    void api.spaces(token).then((result) => {
      if (generation === bootstrapGeneration.current) setKnowledgeSpaces(result.items)
    }).catch(() => { /* 空间列表拉取失败不阻断启动；来源多选区隐藏即可 */ })
  }, [token])

  // Job 面板轮询：上传版本后索引任务由后台 worker 消费，排队中/完成/失败要及时反映
  useEffect(() => {
    if (!token) return
    const timer = window.setInterval(() => {
      if (window.document.visibilityState !== 'visible') return
      void api.jobs(token).then((result) => setJobs(result.items)).catch(() => { /* 轮询失败保持现状，下一次重试 */ })
    }, 15_000)
    return () => window.clearInterval(timer)
  }, [token])

  useEffect(() => {
    sessionStorage.setItem('doc-agent-source-ids', JSON.stringify(selectedSourceIds))
  }, [selectedSourceIds])

  useEffect(() => {
    if (projectId) sessionStorage.setItem(sessionKeys.projectId, projectId)
  }, [projectId])

  useEffect(() => {
    if (!token || !projectId) return
    const generation = ++documentsGeneration.current
    const projectChanged = previousProjectId.current !== projectId
    previousProjectId.current = projectId
    const savedDocumentId = projectChanged ? null : sessionStorage.getItem(sessionKeys.documentId)
    const savedVersionId = projectChanged ? null : sessionStorage.getItem(sessionKeys.versionId)
    if (projectChanged) {
      sessionStorage.removeItem(sessionKeys.documentId)
      sessionStorage.removeItem(sessionKeys.versionId)
    }
    setDocuments([])
    setDocument(null)
    setVersions([])
    setSelectedVersion(null)
    setDesiredVersionId(savedVersionId)
    setSource('')
    setSourceVersionId(null)
    setDocumentError('')
    setCitations([])
    void api.documents(token, projectId).then((result) => {
      if (generation !== documentsGeneration.current) return
      setDocuments(result)
      const restored = result.find((item) => item.id === savedDocumentId)
      if (restored) setDocument(restored)
    })
  }, [projectId, token])

  useEffect(() => {
    if (document) sessionStorage.setItem(sessionKeys.documentId, document.id)
  }, [document])

  useEffect(() => {
    if (!token || !document) {
      versionsGeneration.current += 1
      return
    }
    const generation = ++versionsGeneration.current
    const documentId = document.id
    const targetId = desiredVersionId
    setDocumentError('')
    void api.versions(token, documentId).then((result) => {
      if (generation !== versionsGeneration.current || documentId !== document?.id) return
      setVersions(result)
      const restored = result.find((version) => version.id === targetId) ?? result.at(-1)
      if (restored) setSelectedVersion(restored)
    }).catch(() => {
      if (generation === versionsGeneration.current) setDocumentError('版本加载失败，请重新选择文档。')
    })
  }, [document?.id, token, versionLoadRequest])

  useEffect(() => {
    if (selectedVersion) sessionStorage.setItem(sessionKeys.versionId, selectedVersion.id)
  }, [selectedVersion])

  useEffect(() => {
    if (!token || !selectedVersion) {
      sourceGeneration.current += 1
      return
    }
    const generation = ++sourceGeneration.current
    setSource('')
    setSourceVersionId(null)
    void api.versionContent(token, selectedVersion.document_id, selectedVersion.number).then((content) => {
      if (generation === sourceGeneration.current) {
        setSource(content)
        setSourceVersionId(selectedVersion.id)
      }
    }).catch(() => {
      if (generation === sourceGeneration.current) setDocumentError('正文加载失败，请重新选择版本。')
    })
  }, [selectedVersion, token])

  function selectVersion(version: DocumentVersion) {
    if (version.id === selectedVersion?.id && sourceVersionId === version.id) return
    sourceGeneration.current += 1
    setDocumentError('')
    sessionStorage.setItem(sessionKeys.versionId, version.id)
    setDesiredVersionId(version.id)
    setSelectedVersion(version)
    setSource('')
    setSourceVersionId(null)
  }

  function selectDocument(next: Document) {
    if (next.id === document?.id && !documentError) return
    loadDocument(next)
  }

  // 强制加载目标文档并选中最新的不可变版本（供工作台就地切换目标文档使用，绕过"当前已选"短路）
  function loadDocument(next: Document) {
    versionsGeneration.current += 1
    sourceGeneration.current += 1
    sourceNavigationGeneration.current += 1
    sessionStorage.setItem(sessionKeys.documentId, next.id)
    sessionStorage.removeItem(sessionKeys.versionId)
    setDesiredVersionId(null)
    setDocument(next)
    setSelectedVersion(null)
    setVersions([])
    setSource('')
    setSourceVersionId(null)
    setVersionLoadRequest((value) => value + 1)
  }

  function clearTarget() {
    versionsGeneration.current += 1
    sourceGeneration.current += 1
    setDocument(null)
    setSelectedVersion(null)
    setVersions([])
    setSource('')
    setSourceVersionId(null)
    sessionStorage.removeItem(sessionKeys.documentId)
    sessionStorage.removeItem(sessionKeys.versionId)
  }

  async function login(username: string, password: string) {
    const accessToken = await api.login(username, password)
    sessionStorage.setItem('doc-agent-token', accessToken)
    setToken(accessToken)
  }

  function logout() {
    bootstrapGeneration.current += 1
    documentsGeneration.current += 1
    versionsGeneration.current += 1
    sourceGeneration.current += 1
    sourceNavigationGeneration.current += 1
    if (user) {
      const messagePrefix = `doc-agent-messages-${user.id}-`
      const draftPrefix = `doc-agent-draft-${user.id}-`
      Object.keys(sessionStorage)
        .filter((key) => key.startsWith(messagePrefix) || key.startsWith(draftPrefix))
        .forEach((key) => sessionStorage.removeItem(key))
    }
    sessionStorage.removeItem('doc-agent-token')
    Object.values(sessionKeys).forEach((key) => sessionStorage.removeItem(key))
    setToken('')
    setUser(null)
    setProjectId('')
    setProjects([])
    setDocuments([])
    setDocument(null)
    setVersions([])
    setSelectedVersion(null)
    setSource('')
    setSourceVersionId(null)
    setCitations([])
    setJobs([])
  }

  function navigate(next: string) {
    if (next !== 'documents') setKnowledgeReturnDocumentId(null)
    window.location.hash = next
    setView(next)
  }

  async function openCitation(citation: Citation) {
    await openSource(citation.document_id, citation.version_id)
    navigate('documents')
  }

  async function openSource(documentId: string, versionId: string, fromKnowledge = false) {
    const generation = ++sourceNavigationGeneration.current
    const matchedDocument = documents.find((item) => item.id === documentId) ?? await api.document(token, documentId)
    if (generation !== sourceNavigationGeneration.current) return
    const sameDocument = matchedDocument.id === document?.id
    sessionStorage.setItem(sessionKeys.documentId, matchedDocument.id)
    sessionStorage.setItem(sessionKeys.versionId, versionId)
    setKnowledgeReturnDocumentId(fromKnowledge ? matchedDocument.id : null)
    setDesiredVersionId(versionId)
    setSelectedVersion(null)
    setVersions([])
    setSource('')
    setSourceVersionId(null)
    setDocument(matchedDocument)
    if (sameDocument) setVersionLoadRequest((current) => current + 1)
  }

  const knowledgeSources: KnowledgeSource[] = useMemo(
    () => knowledgeSpaces.map((space) => ({
      id: space.id,
      kind: space.kind,
      label: `${displayLabel(zhCN.space, space.kind)}${space.owner_id === user?.id ? '（我的）' : ''}`,
    })),
    [knowledgeSpaces, user?.id],
  )

  if (!token || !user) return <LoginView onLogin={login} />

  const currentProject = projects.find((item) => item.id === projectId)
  const versionLabel = document && selectedVersion ? `《${document.title}》v${selectedVersion.number}` : undefined
  const agentContext: AgentContext | undefined = currentProject
    ? { projectName: currentProject.name, documentTitle: document?.title ?? null, versionLabel: selectedVersion ? `v${selectedVersion.number}` : null }
    : undefined
  // 选中版本时以文档所属项目为准，避免与侧栏项目选择不一致导致后端校验失败
  const chatProjectId = document && selectedVersion ? document.project_id : projectId || undefined
  const currentSourceIds = selectedSourceIds.filter((id) => knowledgeSpaces.some((space) => space.id === id))
  function toggleSource(id: string) {
    setSelectedSourceIds((current) => current.includes(id) ? current.filter((item) => item !== id) : [...current, id])
  }

  return <div className={railOpen ? 'app-shell' : 'app-shell rail-closed'}>
    <nav className="side-nav" aria-label="主导航">
      <div className="brand">Doc Agent</div>
      {navigation.filter(([id]) => id !== 'reviews' || !isAdmin(user)).map(([id, label]) => <button type="button" className={view === id ? 'active' : ''} key={id} onClick={() => navigate(id)}>{label}</button>)}
      {isAdmin(user) && <>
        <button type="button" className={['management', 'reviews', 'governance'].includes(view) ? 'active' : ''} onClick={() => navigate('management')}>管理</button>
        {['management', 'reviews', 'governance'].includes(view) && <div className="management-nav" role="group" aria-label="管理导航"><button type="button" aria-current={view === 'reviews' ? 'page' : undefined} onClick={() => navigate('reviews')}>待我评审</button><button type="button" aria-current={view === 'governance' ? 'page' : undefined} onClick={() => navigate('governance')}>知识库治理</button></div>}
      </>}
      {/* 上级（reviewer）也有治理权，但管理页与系统评审队列仅管理员可见；管理员入口已含治理，避免重复渲染 */}
      {!isAdmin(user) && canGovernKnowledge(user) && <button type="button" className={view === 'governance' ? 'active' : ''} onClick={() => navigate('governance')}>知识库治理</button>}
      <label className="project-select">项目
        <select value={projectId} onChange={(event) => setProjectId(event.target.value)}>
          <option value="">请选择项目</option>
          {projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}
        </select>
      </label>
      <div className="account">
        <strong>{user.username}</strong>
        <span>{displayLabel(zhCN.role, user.role)}</span>
        <button type="button" onClick={logout}>退出登录</button>
      </div>
    </nav>
    {view === 'workspace' && <AgentWorkspace key={`${user.id}-${projectId}`} context={agentContext} userId={user.id} sessionKey={projectId} knowledgeSources={knowledgeSources} selectedSourceIds={currentSourceIds} onToggleSource={toggleSource} targetDocuments={documents.map((item) => ({ id: item.id, title: item.title }))} activeDocumentId={document?.id ?? null} onSelectTarget={(documentId) => { if (!documentId) { clearTarget(); return } const target = documents.find((item) => item.id === documentId); if (target) loadDocument(target) }} onSend={(text, options) => api.chat(token, { text, confirmed: options.confirmed, idempotency_key: options.idempotencyKey, project_id: chatProjectId, document_version_id: selectedVersion?.id, knowledge_space_ids: currentSourceIds })} onCitations={setCitations} />}
    {view === 'knowledge' && <KnowledgeManager token={token} currentUserId={user.id} selectedVersionId={selectedVersion?.id} selectedVersionLabel={versionLabel} canGovern={canGovernKnowledge(user)} onOpenGovernance={() => navigate('governance')} onOpenHit={(hit) => { void openSource(hit.document_id, hit.version_id, true).then(() => navigate('documents')) }} />}
    {view === 'governance' && (canGovernKnowledge(user) ? <KnowledgeGovernance token={token} onBack={() => navigate('knowledge')} /> : <main className="management-workspace"><h1>知识库治理</h1><p role="status">当前账号没有治理权限。</p></main>)}
    {view === 'management' && (isAdmin(user) ? <ManagementWorkspace key={`${user.id}-${projectId}`} token={token} projectId={projectId} currentUserId={user.id} /> : <main className="management-workspace"><h1>管理</h1><p role="status">当前账号没有管理权限。</p></main>)}
    {view === 'reviews' && <ReviewWorkspace key={`${user.id}-${projectId}`} token={token} projectId={projectId} documents={reviewDocuments} currentUserId={user.id} onOpenDocument={async (documentId, versionId) => { await openSource(documentId, versionId); navigate('documents') }} />}
    {view === 'documents' && <div className="content-columns">
      <aside className="document-list">
        <h2>文档</h2>
        {documents.length > 0 && <input type="search" className="document-filter" aria-label="筛选文档" placeholder="筛选文档…" value={documentFilter} onChange={(event) => setDocumentFilter(event.target.value)} />}
        <div className="document-list-scroll">
          {documents.length === 0 && <p className="muted">当前项目还没有文档。</p>}
          {documents.length > 0 && filteredDocuments.length === 0 && <p className="muted">没有匹配「{documentFilter}」的文档。</p>}
          {filteredDocuments.map((item) => <button type="button" className={item.id === document?.id ? 'selected' : ''} key={item.id} onClick={() => { selectDocument(item); navigate('documents') }}>{item.title}</button>)}
        </div>
        {projectId && <NewDocumentForm token={token} projectId={projectId} onCreated={(created) => { setDocuments((current) => [...current, created]); selectDocument(created) }} />}
      </aside>
      <div className="document-area">
        {knowledgeReturnDocumentId && document?.id === knowledgeReturnDocumentId && <button type="button" className="text-action knowledge-return" onClick={() => navigate('knowledge')}><ArrowLeft size={16} aria-hidden="true" />返回知识库</button>}
        {documentError && <p role="alert" className="error">{documentError}</p>}
        <DocumentHub key={document?.id} token={token} document={document} versions={versions} source={source} sourceReady={Boolean(selectedVersion && sourceVersionId === selectedVersion.id)} selectedVersion={selectedVersion} onSelectVersion={selectVersion} onVersionUploaded={(version) => { setVersions((current) => current.some((item) => item.id === version.id) ? current : [...current, version]); selectVersion(version) }} currentUserId={user.id} onAgentSend={(text, options) => api.chat(token, { text, confirmed: options.confirmed, idempotency_key: options.idempotencyKey, project_id: document?.project_id, document_version_id: selectedVersion?.id })} onAgentCitations={setCitations} />
      </div>
    </div>}
    {railOpen
      ? <div className="right-rail">
          <button type="button" className="rail-collapse" onClick={() => setRailOpen(false)}>收起面板 ›</button>
          <CitationPanel citations={citations} onOpenCitation={openCitation} />
          <JobStatus jobs={jobs} onRetry={async (jobId) => { const next = await api.retryJob(token, jobId); setJobs((current) => current.map((job) => job.id === next.id ? next : job)) }} />
        </div>
      : <button type="button" className="rail-toggle" onClick={() => setRailOpen(true)}>引用与任务</button>}
  </div>
}
