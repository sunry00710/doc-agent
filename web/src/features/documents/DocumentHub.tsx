import { useEffect, useRef, useState } from 'react'
import { api } from '../../api/client'
import type { Document, DocumentVersion } from '../../api/client'
import { ComparisonView } from '../comparison/ComparisonView'
import { WritingContractForm } from '../contracts/WritingContractForm'
import { DocumentReviewStatus } from './DocumentReviewStatus'
import { UploadVersionForm } from './UploadVersionForm'
import { VersionList } from './VersionList'
import { AgentWorkspace } from '../agent/AgentWorkspace'
import type { ChatResponse, Citation } from '../../api/client'
import { useProjectAccess } from '../projects/useProjectAccess'

const tabs = [
  ['source', '正文'],
  ['contract', '写作契约'],
  ['compare', '版本对比'],
] as const

type Props = {
  token: string
  document: Document | null
  versions: DocumentVersion[]
  source: string
  sourceReady: boolean
  selectedVersion: DocumentVersion | null
  onSelectVersion: (version: DocumentVersion) => void
  onVersionUploaded: (version: DocumentVersion) => void
  currentUserId: string
  onAgentSend?: (text: string, options: { confirmed: boolean; idempotencyKey?: string }) => Promise<ChatResponse>
  onAgentCitations?: (citations: Citation[]) => void
}

export function DocumentHub({ token, document, versions, source, sourceReady, selectedVersion, onSelectVersion, onVersionUploaded, currentUserId, onAgentSend, onAgentCitations }: Props) {
  const access = useProjectAccess(token, document?.project_id, currentUserId)
  const [tab, setTab] = useState('source')
  const [draft, setDraft] = useState(source)
  const [savingDraft, setSavingDraft] = useState(false)
  const [draftNotice, setDraftNotice] = useState('')
  const [selection, setSelection] = useState('')
  const draftKey = `doc-agent-draft-${currentUserId}-${document?.id}-${selectedVersion?.id}`
  const initializedDraft = useRef('')
  useEffect(() => {
    if (!sourceReady || !selectedVersion || initializedDraft.current === draftKey) return
    initializedDraft.current = draftKey
    try { setDraft(sessionStorage.getItem(draftKey) ?? source) }
    catch { setDraft(source) }
    setSelection('')
  }, [source, sourceReady, draftKey, selectedVersion])

  function updateDraft(text: string, successNotice = '') {
    setDraft(text)
    setDraftNotice(successNotice)
    try { sessionStorage.setItem(draftKey, text) }
    catch { setDraftNotice('本地草稿保存失败，请先保存为新版本再离开。') }
  }

  async function saveDraft() {
    if (!document || !selectedVersion || !sourceReady || !access.canEdit || savingDraft) return
    setSavingDraft(true)
    setDraftNotice('')
    try {
      const file = new File([draft], `v${(versions.at(-1)?.number ?? 0) + 1}-draft.md`, { type: 'text/markdown' })
      const version = await api.uploadVersion(token, document.id, file)
      sessionStorage.removeItem(draftKey)
      onVersionUploaded(version)
      setDraftNotice(`已保存为 v${version.number}。`)
    } catch { setDraftNotice('草稿保存失败，请稍后重试。') }
    finally { setSavingDraft(false) }
  }
  if (!document) return <main className="document-workspace"><div className="empty-state"><h1>选择文档</h1><p>请在文档页面选择文档，打开对应的不可变工作区。</p></div></main>
  return <main className="document-workspace">
    <header><p className="eyebrow">当前文档</p><h1>{document.title}</h1><p className="muted">{document.domain} · {document.document_type}</p></header>
    {/* 仅打印可见：textarea 打印效果差，导出 PDF 时改用本层渲染当前草稿正文 */}
    {selectedVersion && sourceReady && <section className="print-document">
      <h1>{document.title}</h1>
      <p className="print-meta">{document.domain} · {document.document_type} · v{selectedVersion.number} · 导出于 {new Date().toLocaleDateString('zh-CN')}</p>
      {draft !== source && <p className="print-meta">（导出内容为未保存的本地草稿）</p>}
      <pre>{draft}</pre>
    </section>}
    <DocumentReviewStatus token={token} documentId={document.id} versions={versions} selectedVersion={selectedVersion} canSubmit={access.canSubmit && sourceReady} dirty={draft !== source} />
    {access.error && <p className="error" role="alert">{access.error}</p>}
    <div className="hub-tabs" role="tablist" aria-label="文档视图">{tabs.map(([id, label]) => <button type="button" role="tab" aria-selected={tab === id} className={tab === id ? 'selected' : ''} key={id} onClick={() => setTab(id)}>{label}</button>)}</div>
    <aside className="version-column">
      <VersionList versions={versions} selectedId={selectedVersion?.id ?? null} onSelect={onSelectVersion} />
      {access.canEdit && <UploadVersionForm token={token} documentId={document.id} nextNumber={(versions.at(-1)?.number ?? 0) + 1} onUploaded={onVersionUploaded} />}
    </aside>
    <div className="tab-content">
      {tab === 'source' && <section className="editor-panel">
        <div className="editor-toolbar"><strong>{selectedVersion ? `编辑草稿 · 基于 v${selectedVersion.number}` : '编辑草稿'}</strong><span className="muted">{!sourceReady ? '正文加载中' : draft !== source ? '草稿已修改' : '与版本一致'}</span>{selectedVersion && sourceReady && <button type="button" className="print-action" onClick={() => window.print()}>导出 PDF</button>}</div>
        <textarea className="document-editor" aria-label="正文草稿" value={sourceReady ? draft : ''} onChange={(event) => updateDraft(event.target.value)} onSelect={(event) => { const editor = event.currentTarget; if (editor.selectionEnd > editor.selectionStart) setSelection(editor.value.slice(editor.selectionStart, editor.selectionEnd)) }} placeholder="请选择版本后开始编辑…" disabled={!selectedVersion || !sourceReady || !access.canEdit || savingDraft} />
        <div className="action-row"><button type="button" disabled={!selectedVersion || !sourceReady || !access.canEdit || !draft.trim() || draft === source || savingDraft} onClick={() => void saveDraft()}>{savingDraft ? '保存中…' : '保存为新版本'}</button>{selection && <span className="muted">已选：{selection.slice(0, 80)}{selection.length > 80 ? '…' : ''}</span>}{draftNotice && <span className="muted" role="status">{draftNotice}</span>}</div>
        {onAgentSend && <AgentWorkspace compact userId={currentUserId} context={document && selectedVersion ? { projectName: '', documentTitle: document.title, versionLabel: `v${selectedVersion.number}` } : undefined} sessionKey={`doc-${document.id}`} onSend={async (text, options) => { const outgoing = selection ? `${text}\n\n请重点分析以下选中文本：\n${selection}` : text; setSelection(''); return onAgentSend(outgoing, options) }} onCitations={onAgentCitations ?? (() => {})} onApplySuggestion={access.canEdit && sourceReady ? (suggestion, kind) => { updateDraft(kind === 'draft' ? suggestion : draft + `\n\n【Agent 建议】\n${suggestion}`, kind === 'draft' ? '已将 Agent 草稿填入编辑器，确认后可点「保存为新版本」。' : '') } : undefined} />}
      </section>}
      {tab === 'contract' && selectedVersion && <WritingContractForm token={token} documentId={document.id} documentType={document.document_type} canConfirm={access.canReview} source={source} />}
      {tab === 'compare' && <ComparisonView token={token} documentId={document.id} versions={versions} />}
    </div>
  </main>
}
