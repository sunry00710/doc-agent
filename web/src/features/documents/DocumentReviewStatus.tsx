import { useEffect, useState } from 'react'
import { Send } from 'lucide-react'
import { api } from '../../api/client'
import type { ApiError, DocumentVersion, ReviewDetail } from '../../api/client'
import { displayError, displayLabel, zhCN } from '../../app/strings'

type Props = {
  token: string
  documentId: string
  versions: DocumentVersion[]
  selectedVersion: DocumentVersion | null
  canSubmit: boolean
  dirty: boolean
}

export function DocumentReviewStatus({ token, documentId, versions, selectedVersion, canSubmit, dirty }: Props) {
  const [review, setReview] = useState<ReviewDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [revision, setRevision] = useState(0)
  useEffect(() => {
    let active = true
    setLoading(true)
    setReview(null)
    setError('')
    void api.reviews(token, documentId).then(async (items) => {
      const matched = items.find((item) => item.version_id === selectedVersion?.id)
        ?? items.find((item) => item.state === 'changes_requested')
      const detail = matched ? await api.review(token, matched.id) : null
      if (active) setReview(detail)
    }).catch(() => {
      if (active) setError('评审状态加载失败。')
    }).finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [token, documentId, selectedVersion?.id, revision])

  const bound = versions.find((version) => version.id === review?.version_id)
  const latest = versions.at(-1)
  const resubmit = review?.state === 'changes_requested'
  const canResubmit = resubmit && bound && latest && latest.number > bound.number && latest.id === selectedVersion?.id
  const showSubmit = !review || review.state === 'draft' || resubmit

  async function submit() {
    if (!selectedVersion || !canSubmit || busy || loading || dirty || (resubmit && !canResubmit)) return
    setBusy(true)
    setError('')
    try {
      const target = review ?? await api.createReview(token, documentId, selectedVersion.id)
      await api.transitionReview(token, target.id, resubmit ? 'resubmitted' : 'submitted', target.workflow_revision)
      setRevision((value) => value + 1)
    } catch (reason) {
      setError(displayError((reason as Partial<ApiError>).code, '提交失败，请刷新评审状态后重试。'))
    } finally { setBusy(false) }
  }

  return <section className="document-review-status" aria-label="文档评审状态">
    <div className="document-status-line">
      <strong>{loading ? '正在加载评审状态…' : review ? displayLabel(zhCN.reviewState, review.state) : '未提交评审'}</strong>
      {review && <span>绑定版本：{bound ? `v${bound.number}` : review.version_id.slice(0, 8)}</span>}
      {!loading && !error && canSubmit && showSubmit && <button type="button" onClick={() => void submit()} disabled={busy || dirty || !selectedVersion || (resubmit && !canResubmit)}>
        <Send size={16} aria-hidden="true" />{busy ? '提交中…' : resubmit ? `重新提交 v${latest?.number ?? ''}` : `提交 v${selectedVersion?.number ?? ''} 评审`}
      </button>}
      <button type="button" className="text-action" onClick={() => setRevision((value) => value + 1)} disabled={loading || busy}>刷新状态</button>
    </div>
    {dirty && showSubmit && <p className="muted">草稿尚未保存为新版本。</p>}
    {resubmit && !canResubmit && !dirty && <p className="muted">待返修：{latest && bound && latest.number > bound.number ? `请选择 v${latest.number} 重新提交。` : '尚无新的返修版本。'}</p>}
    {review && <details className="document-comments"><summary>修改意见（{review.comments.length}）</summary>
      {review.comments.length === 0 && <p className="muted">暂无意见。</p>}
      {review.comments.map((comment) => <article className="review-comment" key={comment.id}>
        <span>v{versions.find((version) => version.id === comment.version_id)?.number ?? '?'} · {displayLabel(zhCN.status, comment.status)}</span>
        <p>{comment.text}</p>
      </article>)}
    </details>}
    {error && <p role="alert" className="error">{error}</p>}
  </section>
}
