import { useEffect, useState } from 'react'
import { RefreshCw } from 'lucide-react'
import type { Document, Review } from '../../api/client'
import { api } from '../../api/client'
import { displayLabel, zhCN } from '../../app/strings'

type ReviewQueueProps = {
  token: string
  documents: Document[]
  selectedReviewId: string | null
  currentUserId: string
  refreshKey: number
  onSelect: (document: Document, review: Review) => void
}

type QueueItem = { document: Document; review: Review; versionNumber?: number }
const ACTIONABLE_STATES = new Set(['submitted', 'in_review', 'resubmitted'])

export function ReviewQueue({ token, documents, selectedReviewId, currentUserId, refreshKey, onSelect }: ReviewQueueProps) {
  const [items, setItems] = useState<QueueItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [filter, setFilter] = useState('mine')
  const [reload, setReload] = useState(0)

  useEffect(() => {
    let active = true
    setLoading(true)
    setItems([])
    setError('')
    void Promise.all(documents.map(async (document) => {
      const reviews = await api.reviews(token, document.id)
      const tasks = reviews.filter((review) => ACTIONABLE_STATES.has(review.state) && (review.reviewer_id === currentUserId || (!review.reviewer_id && review.state === 'submitted')))
      const versions = tasks.length ? await api.versions(token, document.id) : []
      return tasks.map((review) => ({ document, review, versionNumber: versions.find((version) => version.id === review.version_id)?.number }))
    })).then((groups) => {
      if (active) setItems(groups.flat())
    }).catch(() => {
      if (active) setError('评审队列加载失败。')
    }).finally(() => {
      if (active) setLoading(false)
    })
    return () => { active = false }
  }, [documents, token, currentUserId, refreshKey, reload])

  useEffect(() => {
    if (items.some(({ review }) => review.id === selectedReviewId && review.reviewer_id === currentUserId)) setFilter('mine')
  }, [items, selectedReviewId, currentUserId])

  const mine = items.filter(({ review }) => review.reviewer_id === currentUserId)
  const unassigned = items.filter(({ review }) => !review.reviewer_id)
  const visible = filter === 'mine' ? mine : unassigned

  return <aside className="review-queue" aria-label="评审队列">
    <header className="queue-heading"><h2>评审任务</h2><button type="button" className="icon-button" title="刷新评审队列" aria-label="刷新评审队列" onClick={() => setReload((value) => value + 1)} disabled={loading}><RefreshCw size={16} /></button></header>
    <div role="tablist" aria-label="任务范围" className="task-filters">
      <button role="tab" aria-selected={filter === 'mine'} onClick={() => setFilter('mine')}>待我评审 {mine.length}</button>
      <button role="tab" aria-selected={filter === 'unassigned'} onClick={() => setFilter('unassigned')}>待领取 {unassigned.length}</button>
    </div>
    {loading && <p className="muted">正在加载评审队列…</p>}
    {error && <p role="alert" className="error">{error}</p>}
    {!loading && !error && visible.length === 0 && <p className="muted">{filter === 'mine' ? '暂无待我评审的任务。' : '暂无待领取的任务。'}</p>}
    <div className="review-queue-list">
      {visible.map(({ document, review, versionNumber }) => <button type="button" key={review.id} className={review.id === selectedReviewId ? 'selected' : ''} onClick={() => onSelect(document, review)}>
        <strong>{document.title}</strong>
        <span>{versionNumber ? `v${versionNumber}` : review.version_id.slice(0, 8)} · {displayLabel(zhCN.reviewState, review.state)}</span>
      </button>)}
    </div>
  </aside>
}
