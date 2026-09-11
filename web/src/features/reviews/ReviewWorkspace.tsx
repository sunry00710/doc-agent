import { useState } from 'react'
import type { Document, Review } from '../../api/client'
import { useProjectAccess } from '../projects/useProjectAccess'
import { ReviewQueue } from './ReviewQueue'
import { ReviewTaskPanel } from './ReviewTaskPanel'

type Props = {
  token: string
  projectId: string
  documents: Document[]
  currentUserId: string
  onOpenDocument: (documentId: string, versionId: string) => Promise<void>
}

export function ReviewWorkspace({ token, projectId, documents, currentUserId, onOpenDocument }: Props) {
  const access = useProjectAccess(token, projectId, currentUserId)
  const [selected, setSelected] = useState<{ document: Document; review: Review } | null>(null)
  const [refreshKey, setRefreshKey] = useState(0)
  if (access.loading) return <main className="review-task"><p role="status">正在加载项目权限…</p></main>
  if (!access.canReview) return <main className="review-task"><h1>待我评审</h1><p role="status">{access.error ?? '当前项目未授予你评审权限。'}</p></main>
  return <div className="review-columns">
    <ReviewQueue token={token} documents={documents} selectedReviewId={selected?.review.id ?? null} currentUserId={currentUserId} refreshKey={refreshKey} onSelect={(document, review) => setSelected({ document, review })} />
    {selected
      ? <ReviewTaskPanel key={selected.review.id} token={token} document={selected.document} reviewId={selected.review.id} currentUserId={currentUserId} canReview={access.canReview} onChanged={() => setRefreshKey((value) => value + 1)} onOpenDocument={onOpenDocument} />
      : <main className="review-task"><h1>选择评审任务</h1></main>}
  </div>
}
