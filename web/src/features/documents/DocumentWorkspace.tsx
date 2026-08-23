import { useEffect, useState } from 'react'
import type { Document, DocumentVersion } from '../../api/client'
import { VersionList } from './VersionList'

type Props = { token: string; projectId?: string; onVersion: (document: Document | null, version: DocumentVersion | null, source: string) => void }

export function DocumentWorkspace({ token, projectId, onVersion }: Props) {
  const [documents, setDocuments] = useState<Document[]>([])
  const [selected, setSelected] = useState<Document | null>(null)
  const [versions, setVersions] = useState<DocumentVersion[]>([])
  const [selectedVersion, setSelectedVersion] = useState<DocumentVersion | null>(null)
  const [source, setSource] = useState('')
  const [error, setError] = useState('')

  useEffect(() => { if (!projectId) return; void fetch(`/api/documents?project_id=${encodeURIComponent(projectId)}`, { headers: { Authorization: `Bearer ${token}` } }).then((response) => response.json()).then(setDocuments).catch(() => setError('Documents could not be loaded.')) }, [projectId, token])
  async function chooseDocument(document: Document) { setSelected(document); setSelectedVersion(null); setSource(''); const response = await fetch(`/api/documents/${document.id}/versions`, { headers: { Authorization: `Bearer ${token}` } }); setVersions(await response.json()) }
  async function chooseVersion(version: DocumentVersion) { setSelectedVersion(version); const response = await fetch(`/api/documents/${version.document_id}/versions/${version.number}`, { headers: { Authorization: `Bearer ${token}` } }); const text = await response.text(); setSource(text); onVersion(selected, version, text) }

  return <main className="document-workspace"><header><p className="eyebrow">Document workspace</p><h1>Immutable source and review context</h1></header>{error && <p role="alert" className="error">{error}</p>}<div className="document-grid"><aside className="document-picker"><h2>Documents</h2>{documents.length === 0 ? <p className="muted">Select a project to view documents.</p> : <ul>{documents.map((document) => <li key={document.id}><button type="button" className={selected?.id === document.id ? 'selected' : ''} onClick={() => void chooseDocument(document)}>{document.title}<span>{document.document_type}</span></button></li>)}</ul>}<VersionList versions={versions} selectedId={selectedVersion?.id ?? null} onSelect={(version) => void chooseVersion(version)} /></aside><section className="source-view">{selectedVersion ? <><div className="version-banner"><strong>{selected?.title}</strong><span>v{selectedVersion.number} · {selectedVersion.id}</span><code>{selectedVersion.content_sha256}</code></div><pre className="source-text">{source}</pre></> : <div className="empty-state"><h2>Choose an immutable version</h2><p>Reviews, comparisons, contracts, and promotion actions stay bound to the selected version.</p></div>}</section></div></main>
}
