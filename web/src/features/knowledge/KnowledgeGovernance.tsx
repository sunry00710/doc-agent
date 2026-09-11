import { useCallback, useEffect, useState } from 'react'
import { ArrowLeft, RefreshCw } from 'lucide-react'
import { api, type ApiError, type Promotion } from '../../api/client'
import { displayError, displayLabel, zhCN } from '../../app/strings'

export function KnowledgeGovernance({ token, onBack }: { token: string; onBack: () => void }) {
  const [items, setItems] = useState<Promotion[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [busyId, setBusyId] = useState<string | null>(null)
  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try { setItems((await api.promotions(token)).items.filter((item) => item.can_govern)) }
    catch { setError('知识库治理任务加载失败。') }
    finally { setLoading(false) }
  }, [token])
  useEffect(() => { void load() }, [load])

  async function act(item: Promotion, action: () => Promise<Promotion>) {
    if (busyId || !item.can_govern) return
    setBusyId(item.id)
    setError('')
    try { await action(); await load() }
    catch (reason) { setError(displayError((reason as Partial<ApiError>).code, '治理操作失败，请刷新后重试。')) }
    finally { setBusyId(null) }
  }

  return <main className="knowledge-workspace">
    <header className="review-task-header"><div><p className="eyebrow">治理</p><h1>知识库治理</h1></div>
      <div className="action-row"><button type="button" className="text-action" onClick={onBack}><ArrowLeft size={16} />返回知识库</button>
        <button type="button" className="icon-button" title="刷新治理任务" aria-label="刷新治理任务" disabled={loading || Boolean(busyId)} onClick={() => void load()}><RefreshCw size={16} /></button></div>
    </header>
    {loading && <p role="status">正在加载治理任务…</p>}
    {error && <p className="error" role="alert">{error}</p>}
    {!loading && !error && items.length === 0 && <p className="muted">暂无有权处理的知识库治理任务。</p>}
    {items.map((item) => <article className="promotion-row" key={item.id}>
      <div className="promotion-head"><strong>{item.document_title ?? '文档版本'}{item.version_number != null ? ` v${item.version_number}` : ''}</strong><span>{displayLabel(zhCN.promotionStatus, item.status)}</span></div>
      <span>{displayLabel(zhCN.qualityStatus, item.quality_status)}</span>
      {item.findings.length > 0 && <details><summary>质量检查（{item.findings.length}）</summary>{item.findings.map((finding, index) => <p key={index}>{String(finding.summary ?? finding.evidence ?? finding.category ?? '待复核')}</p>)}</details>}
      <div className="action-row">
        {item.status === 'pending_review' && <><button type="button" disabled={Boolean(busyId) || loading} onClick={() => void act(item, () => api.reviewPromotion(token, item.id, true))}>批准</button><button type="button" disabled={Boolean(busyId) || loading} onClick={() => void act(item, () => api.reviewPromotion(token, item.id, false))}>驳回</button></>}
        {item.status === 'approved' && <button type="button" disabled={Boolean(busyId) || loading} onClick={() => void act(item, () => api.activatePromotion(token, item.id))}>激活索引</button>}
        {item.status === 'indexed' && <button type="button" disabled={Boolean(busyId) || loading} onClick={() => void act(item, () => api.revokePromotion(token, item.id))}>撤销</button>}
      </div>
    </article>)}
  </main>
}
