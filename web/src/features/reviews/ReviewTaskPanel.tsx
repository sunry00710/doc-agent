import { useEffect, useState } from 'react'
import { ArrowUpRight } from 'lucide-react'
import { api } from '../../api/client'
import type { Document, DocumentVersion, ReviewDetail } from '../../api/client'
import { ReviewPanel } from './ReviewPanel'

type Props = {
  token: string
  document: Document
  reviewId: string
  currentUserId: string
  canReview: boolean
  onChanged: () => void
  onOpenDocument: (documentId: string, versionId: string) => Promise<void>
}

export function ReviewTaskPanel({ token, document, reviewId, currentUserId, canReview, onChanged, onOpenDocument }: Props) {
  const [data, setData] = useState<{ review: ReviewDetail; version: DocumentVersion; source: string } | null>(null)
  const [error, setError] = useState('')
  const [revision, setRevision] = useState(0)
  const [loading, setLoading] = useState(true)
  useEffect(() => {
    let active = true
    setLoading(true)
    setError('')
    void Promise.all([api.review(token, reviewId), api.versions(token, document.id)]).then(async ([review, versions]) => {
      const version = versions.find((item) => item.id === review.version_id)
      if (!version || review.document_id !== document.id) throw new Error('Review version mismatch')
      const source = await api.versionContent(token, document.id, version.number)
      if (active) setData({ review, version, source })
    }).catch(() => {
      if (active) setError('评审任务加载失败，请重试。')
    }).finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [token, document.id, reviewId, revision])

  return <main className="review-task">
    <header className="review-task-header">
      <div><p className="eyebrow">评审任务</p><h1>{document.title}</h1></div>
      {data && <button type="button" className="text-action" disabled={loading || Boolean(error)} onClick={() => { void onOpenDocument(document.id, data.review.version_id).catch(() => setError('文档打开失败。')) }}><ArrowUpRight size={16} aria-hidden="true" />打开文档工作区</button>}
    </header>
    {loading && <p role="status">正在加载评审版本…</p>}
    {error && <div role="alert"><p className="error">{error}</p><button type="button" onClick={() => setRevision((value) => value + 1)}>重新加载</button></div>}
    {data && <ReviewPanel token={token} review={data.review} source={data.source} selectedVersion={data.version} canReview={canReview && !loading && !error} currentUserId={currentUserId} onRefresh={async () => { setRevision((value) => value + 1); onChanged() }} />}
  </main>
}
