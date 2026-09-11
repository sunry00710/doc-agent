import { useState } from 'react'
import { displayError, displayLabel, zhCN } from '../../app/strings'
import { api } from '../../api/client'
import type { ApiError, KnowledgeSpace } from '../../api/client'

type PromotionDialogProps = {
  token: string
  versionId: string
  versionLabel?: string
  spaces: KnowledgeSpace[]
  onClose: () => void
  onCreated: () => void
}

export function PromotionDialog({ token, versionId, versionLabel, spaces, onClose, onCreated }: PromotionDialogProps) {
  const [spaceId, setSpaceId] = useState('')
  const [error, setError] = useState<Partial<ApiError> | null>(null)
  const [busy, setBusy] = useState(false)
  const targets = spaces.filter((space) => space.kind === 'shared' || space.kind === 'standard')

  async function submit() {
    if (!spaceId || busy) {
      setError({ code: 'validation_error', message: '请选择明确的晋升目标。', request_id: '', retryable: false })
      return
    }
    setError(null)
    setBusy(true)
    try {
      await api.createPromotion(token, { version_id: versionId, target_space_id: spaceId })
      onCreated()
    } catch (reason) {
      const apiError = reason as Partial<ApiError>
      setError({
        code: apiError.code ?? 'network_error',
        message: displayError(apiError.code, '晋升申请创建失败。'),
        request_id: apiError.request_id ?? '',
        retryable: apiError.retryable ?? false,
        details: apiError.details,
      })
    } finally {
      setBusy(false)
    }
  }

  return <section className="modal-backdrop"><div className="modal" role="dialog" aria-label="申请知识晋升"><h2>申请知识晋升</h2><p>来源版本：{versionLabel ?? versionId}</p><label>目标知识空间<select value={spaceId} onChange={(event) => setSpaceId(event.target.value)}><option value="">请选择目标</option>{targets.map((space) => <option key={space.id} value={space.id}>{displayLabel(zhCN.space, space.kind)} · {space.id}</option>)}</select></label>{error && <div role="alert" className="error"><p>{error.message}</p>{error.details?.findings?.map((finding) => <div key={`${finding.requirement_id ?? finding.category}-${finding.summary}`}><strong>{finding.blocking ? '阻断' : finding.human_review_required ? '需人工复核' : '质量门发现'}</strong><p>{finding.requirement_id ? `要求：${finding.requirement_id}` : '契约状态'}</p><p>{finding.summary}</p>{finding.evidence && <p>证据：{finding.evidence}</p>}</div>)}</div>}<div><button type="button" onClick={onClose}>取消</button><button type="button" onClick={() => void submit()} disabled={!spaceId || busy}>{busy ? '提交中…' : '确认申请'}</button></div></div></section>
}
