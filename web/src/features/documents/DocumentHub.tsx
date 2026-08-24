import { useState } from 'react'
import type { Document, DocumentVersion, ReviewDetail } from '../../api/client'
import { ComparisonView } from '../comparison/ComparisonView'
import { WritingContractForm } from '../contracts/WritingContractForm'
import { ReviewPanel } from '../reviews/ReviewPanel'
import { UploadVersionForm } from './UploadVersionForm'
import { VersionList } from './VersionList'

const tabs = [
  ['source', '正文'],
  ['review', '评审'],
  ['contract', '写作契约'],
  ['compare', '版本对比'],
] as const

export function DocumentHub({ token, document, versions, source, selectedVersion, onSelectVersion, onVersionUploaded, review, onRefreshReview, onCreateReview, role, currentUserId }: { token: string; document: Document | null; versions: DocumentVersion[]; source: string; selectedVersion: DocumentVersion | null; onSelectVersion: (version: DocumentVersion) => void; onVersionUploaded: (version: DocumentVersion) => void; review: ReviewDetail | null; onRefreshReview: () => Promise<void>; onCreateReview: () => Promise<void>; role: string; currentUserId: string }) {
  const [tab, setTab] = useState('source')
  if (!document) return <main className="document-workspace"><div className="empty-state"><h1>选择文档</h1><p>请在文档页面选择文档，打开对应的不可变工作区。</p></div></main>
  return <main className="document-workspace">
    <header><p className="eyebrow">当前文档</p><h1>{document.title}</h1><p className="muted">{document.domain} · {document.document_type}</p></header>
    <div className="hub-tabs">{tabs.map(([id, label]) => <button type="button" className={tab === id ? 'selected' : ''} key={id} onClick={() => setTab(id)}>{label}</button>)}</div>
    <aside className="version-column">
      <VersionList versions={versions} selectedId={selectedVersion?.id ?? null} onSelect={onSelectVersion} />
      <UploadVersionForm token={token} documentId={document.id} nextNumber={(versions.at(-1)?.number ?? 0) + 1} onUploaded={onVersionUploaded} />
    </aside>
    <div className="tab-content">
      {tab === 'source' && <pre className="source-text">{source || '请选择一个不可变版本。'}</pre>}
      {tab === 'review' && <ReviewPanel token={token} review={review} source={source} selectedVersion={selectedVersion} canReview={role === 'reviewer' || role === 'admin'} currentUserId={currentUserId} onRefresh={onRefreshReview} onCreateReview={onCreateReview} />}
      {tab === 'contract' && selectedVersion && <WritingContractForm token={token} documentId={document.id} documentType={document.document_type} canConfirm={role === 'reviewer' || role === 'admin'} source={source} />}
      {tab === 'compare' && <ComparisonView token={token} versions={versions} />}
    </div>
  </main>
}
