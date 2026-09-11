import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { displayError, displayLabel, zhCN } from '../../app/strings'
import { api } from '../../api/client'
import type { ApiError, DocumentVersion, ReviewDetail } from '../../api/client'

type ReviewPanelProps = {
  token: string
  review: ReviewDetail | null
  source: string
  selectedVersion: DocumentVersion | null
  canReview: boolean
  currentUserId: string
  onRefresh: () => Promise<void>
}

type NextState = { state: string; label: string; reviewerOnly: boolean }

// 与后端 app/reviews/workflow.py 的状态机保持一致
const NEXT_STATES: Record<string, NextState[]> = {
  submitted: [{ state: 'in_review', label: '开始评审', reviewerOnly: true }],
  in_review: [
    { state: 'changes_requested', label: '请求修改', reviewerOnly: true },
    { state: 'approved', label: '批准', reviewerOnly: true },
  ],
  resubmitted: [{ state: 'in_review', label: '继续评审', reviewerOnly: true }],
  archived: [],
}

const COMMENTABLE_STATES = new Set(['in_review', 'resubmitted'])

function selectionOffsets(container: HTMLElement): { start: number; end: number } | null {
  const selection = window.getSelection()
  if (!selection || selection.rangeCount === 0) return null
  const range = selection.getRangeAt(0)
  if (!container.contains(range.commonAncestorContainer)) return null
  const before = document.createRange()
  before.selectNodeContents(container)
  before.setEnd(range.startContainer, range.startOffset)
  const after = document.createRange()
  after.selectNodeContents(container)
  after.setEnd(range.endContainer, range.endOffset)
  const start = before.toString().length
  const end = after.toString().length
  if (end <= start) return null
  return { start, end }
}

function renderHighlighted(source: string, comments: ReviewDetail['comments']) {
  const nodes: Array<string | ReturnType<typeof mark>> = []
  const ranges = comments
    .filter((comment) => comment.source_range.end > comment.source_range.start && comment.source_range.end <= source.length)
    .map((comment) => ({ id: comment.id, start: comment.source_range.start, end: comment.source_range.end }))
    .sort((a, b) => a.start - b.start)
  let cursor = 0
  for (const range of ranges) {
    if (range.start < cursor) continue
    if (range.start > cursor) nodes.push(source.slice(cursor, range.start))
    nodes.push(mark(range.start, source.slice(range.start, range.end)))
    cursor = range.end
  }
  nodes.push(source.slice(cursor))
  return nodes
}

function mark(key: number, text: string) {
  return <mark key={key}>{text}</mark>
}

export function ReviewPanel({ token, review, source, selectedVersion, canReview, currentUserId, onRefresh }: ReviewPanelProps) {
  const [draft, setDraft] = useState('')
  const [error, setError] = useState('')
  const [conflict, setConflict] = useState(false)
  const [busy, setBusy] = useState(false)
  const [selectionError, setSelectionError] = useState('')
  const [lastSelection, setLastSelection] = useState<{ start: number; end: number } | null>(null)
  const [changeDraft, setChangeDraft] = useState('')
  const sourceRef = useRef<HTMLDivElement>(null)

  // 缓存正文中最近一次有效选区：焦点切到评论输入框会折叠原生选区，提交时优先使用缓存
  useEffect(() => {
    if (!review || !sourceRef.current) return
    const handler = () => {
      const container = sourceRef.current
      if (!container) return
      const offsets = selectionOffsets(container)
      if (offsets) setLastSelection(offsets)
    }
    document.addEventListener('selectionchange', handler)
    return () => document.removeEventListener('selectionchange', handler)
  }, [review, source])

  const comments = review?.comments.filter((comment) => comment.version_id === review.version_id) ?? []
  const highlighted = comments.filter((comment) => comment.source_range.end <= source.length)
  const nextStates = review ? NEXT_STATES[review.state] ?? [] : []
  const commentable = Boolean(review) && COMMENTABLE_STATES.has(review!.state)
  const assignedToMe = canReview && review?.reviewer_id === currentUserId
  const boundSourceReady = Boolean(review && selectedVersion?.id === review.version_id)
  useEffect(() => { setLastSelection(null) }, [review?.version_id, source])

  async function handleApiError(reason: unknown, fallback: string, onConflict?: () => Promise<void>) {
    const apiError = reason as Partial<ApiError>
    if (apiError.code === 'version_conflict') {
      setConflict(true)
      if (onConflict) await onConflict()
      return
    }
    setError(displayError(apiError.code, fallback))
  }

  async function transition(state: string) {
    if (!review || !assignedToMe || !boundSourceReady || busy) return
    setError('')
    setBusy(true)
    try {
      await api.transitionReview(token, review.id, state, review.workflow_revision)
      await onRefresh()
    } catch (reason) {
      await handleApiError(reason, '评审状态更新失败。', onRefresh)
    } finally {
      setBusy(false)
    }
  }

  async function requestChanges() {
    if (!review || !assignedToMe || !boundSourceReady || !source || !changeDraft.trim() || busy) return
    setBusy(true); setError('')
    try {
      const offsets = lastSelection ?? { start: 0, end: source.length }
      await api.requestChanges(token, review.id, changeDraft, offsets, review.workflow_revision)
      setChangeDraft(''); setLastSelection(null); await onRefresh()
    } catch (reason) { await handleApiError(reason, '请求修改失败。', onRefresh) } finally { setBusy(false) }
  }

  async function selfAssign() {
    if (!review || !canReview || review.reviewer_id || review.state !== 'submitted' || busy) return
    setError('')
    setBusy(true)
    try {
      await api.assignReviewer(token, review.id, currentUserId, review.workflow_revision)
      await onRefresh()
    } catch (reason) {
      await handleApiError(reason, '评审员分配失败。', onRefresh)
    } finally {
      setBusy(false)
    }
  }

  async function comment(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!review || !assignedToMe || !boundSourceReady || !draft.trim() || busy) return
    setError('')
    setSelectionError('')
    const offsets = (sourceRef.current ? selectionOffsets(sourceRef.current) : null) ?? lastSelection
    if (!offsets) {
      setSelectionError('请先在正文中选中要评论的文字，再添加评论。')
      return
    }
    setBusy(true)
    try {
      await api.addComment(token, review.id, offsets, draft, review.workflow_revision)
      setDraft('')
      setLastSelection(null)
      await onRefresh()
    } catch (reason) {
      await handleApiError(reason, '审核意见保存失败。', onRefresh)
    } finally {
      setBusy(false)
    }
  }

  return <section className="feature-panel review-panel">
    <p className="eyebrow">评审</p>
    <h2>{review ? displayLabel(zhCN.reviewState, review.state) : '未发起评审'}</h2>
    {review
      ? <p className="muted">绑定版本：{selectedVersion && selectedVersion.id === review.version_id ? `v${selectedVersion.number}` : `${review.version_id.slice(0, 8)}…`} · 工作流修订号：{review.workflow_revision}{review.reviewer_id ? (review.reviewer_id === currentUserId ? ' · 你是本评审的评审员' : ' · 评审员已分配') : ' · 尚未分配评审员'}</p>
      : selectedVersion
        ? <p className="muted">当前选中 v{selectedVersion.number}，可对该版本发起评审。</p>
        : <p className="muted">请先在左侧选择一个不可变版本。</p>}
    {canReview && review?.state === 'submitted' && !review.reviewer_id && <div className="action-row"><button type="button" onClick={() => void selfAssign()} disabled={busy}>领取评审任务</button></div>}
    {assignedToMe && boundSourceReady && nextStates.length > 0 && <div className="action-row" aria-label="评审流转">
      {nextStates.map((next) => (canReview || !next.reviewerOnly) && next.state !== 'changes_requested' && <button type="button" key={next.state} onClick={() => void transition(next.state)} disabled={busy}>{next.label}</button>)}
      {canReview && review?.state === 'in_review' && <><textarea aria-label="请求修改意见" value={changeDraft} onChange={(e) => setChangeDraft(e.target.value)} placeholder="填写请求修改意见" disabled={busy} /><button type="button" onClick={() => void requestChanges()} disabled={!changeDraft.trim() || busy}>请求修改</button></>}
    </div>}
    {review?.state === 'approved' && <p className="muted">评审已通过。</p>}
    {review?.state === 'changes_requested' && <p className="muted">等待作者返修。</p>}
    {review && !boundSourceReady && <p role="status">正在加载绑定版本…</p>}
    {review && boundSourceReady && source && <>
      <p className="muted">正文与评论锚点（选中文字后添加评论）：</p>
      <div className="source-text review-source" ref={sourceRef}>{renderHighlighted(source, comments)}</div>
    </>}
    {highlighted.map((comment) => <article key={comment.id} className="review-comment">
      <strong>{displayLabel(zhCN.status, comment.status)}</strong>
      <q>{source.slice(comment.source_range.start, comment.source_range.end)}</q>
      <p>{comment.text}</p>
      <span>锚点 {comment.source_range.start}–{comment.source_range.end}</span>
    </article>)}
    {assignedToMe && boundSourceReady && review && (commentable
      ? <form className="comment-form" onSubmit={comment}>
          <label htmlFor="review-comment">审核意见（针对正文中选中的文字）</label>
          {lastSelection && <p className="muted">当前锚点文字：<q>{source.slice(lastSelection.start, lastSelection.end)}</q>（{lastSelection.start}–{lastSelection.end}）</p>}
          <textarea id="review-comment" aria-label="审核意见" value={draft} onChange={(event) => setDraft(event.target.value)} placeholder="先在正文中选中相关文字，再填写意见" disabled={busy} />
          <button type="submit" disabled={!draft.trim() || busy}>{busy ? '保存中…' : '添加意见'}</button>
        </form>
      : <p className="muted">当前状态下无法添加评论（仅“审核中/已重新提交”可评论）。</p>)}
    {selectionError && <p className="error" role="alert">{selectionError}</p>}
    {conflict && <p className="conflict" role="alert">审核内容已发生变化。你的草稿已保留，请查看刷新后的状态后再重试。</p>}
    {error && <p className="error" role="alert">{error}</p>}
  </section>
}
