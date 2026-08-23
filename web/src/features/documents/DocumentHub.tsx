import { useState } from 'react'
import type { Document, DocumentVersion, ReviewDetail } from '../../api/client'
import { ComparisonView } from '../comparison/ComparisonView'
import { WritingContractForm } from '../contracts/WritingContractForm'
import { ReviewPanel } from '../reviews/ReviewPanel'
import { VersionList } from './VersionList'

export function DocumentHub({ token, document, versions, source, selectedVersion, onSelectVersion, review, onRefreshReview, role }: { token: string; document: Document | null; versions: DocumentVersion[]; source: string; selectedVersion: DocumentVersion | null; onSelectVersion: (version: DocumentVersion) => void; review: ReviewDetail | null; onRefreshReview: () => Promise<void>; role: string }) {
  const [tab, setTab] = useState('source'); if (!document) return <main className="document-workspace"><div className="empty-state"><h1>Select a document</h1><p>Choose a document from the Documents view to open its immutable workspace.</p></div></main>
  return <main className="document-workspace"><header><p className="eyebrow">Selected document</p><h1>{document.title}</h1><p className="muted">{document.domain} · {document.document_type}</p></header><div className="hub-tabs">{['source', 'review', 'contract', 'compare'].map((name) => <button type="button" className={tab === name ? 'selected' : ''} key={name} onClick={() => setTab(name)}>{name}</button>)}</div><VersionList versions={versions} selectedId={selectedVersion?.id ?? null} onSelect={onSelectVersion} />{tab === 'source' && <pre className="source-text">{source || 'Select an immutable version.'}</pre>}{tab === 'review' && <ReviewPanel token={token} review={review} source={source} canReview={role === 'reviewer' || role === 'admin'} onRefresh={onRefreshReview} />}{tab === 'contract' && selectedVersion && <WritingContractForm token={token} documentId={document.id} documentType={document.document_type} canConfirm={role === 'reviewer' || role === 'admin'} />}{tab === 'compare' && <ComparisonView token={token} versions={versions} />}</main>
}
