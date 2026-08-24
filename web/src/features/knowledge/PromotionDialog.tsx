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
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const targets = spaces.filter((space) => space.kind === 'shared' || space.kind === 'standard')

  async function submit() {
    if (!spaceId || busy) {
      setError('请选择明确的晋升目标。')
      return
    }
    setError('')
    setBusy(true)
    try {
      await api.createPromotion(token, { version_id: versionId, target_space_id: spaceId, findings: [], public_authority: false, authority_level: 0 })
      onCreated()
    } catch (reason) {
      setError(displayError((reason as Partial<ApiError>).code, '晋升申请创建失败。'))
    } finally {
      setBusy(false)
    }
  }

  return <section className="modal-backdrop"><div className="modal" role="dialog" aria-label="申请知识晋升"><h2>申请知识晋升</h2><p>来源版本：{versionLabel ?? versionId}</p><label>目标知识空间<select value={spaceId} onChange={(event) => setSpaceId(event.target.value)}><option value="">请选择目标</option>{targets.map((space) => <option key={space.id} value={space.id}>{displayLabel(zhCN.space, space.kind)} · {space.id}</option>)}</select></label>{error && <p role="alert" className="error">{error}</p>}<div><button type="button" onClick={onClose}>取消</button><button type="button" onClick={() => void submit()} disabled={!spaceId || busy}>{busy ? '提交中…' : '确认申请'}</button></div></div></section>
}
