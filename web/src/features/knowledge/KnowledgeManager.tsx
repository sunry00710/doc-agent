import { useCallback, useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { displayError, displayLabel, zhCN } from '../../app/strings'
import { api } from '../../api/client'
import type { ApiError, KnowledgeSpace, Promotion, SearchHit } from '../../api/client'
import { PromotionDialog } from './PromotionDialog'

type KnowledgeManagerProps = {
  token: string
  role: string
  currentUserId: string
  selectedVersionId?: string
  selectedVersionLabel?: string
}

// 空间分级展示顺序：个人 → 项目 → 共享 → 规范
const SPACE_ORDER: Record<string, number> = { personal: 0, project: 1, shared: 2, standard: 3 }

export function KnowledgeManager({ token, role, currentUserId, selectedVersionId, selectedVersionLabel }: KnowledgeManagerProps) {
  const [query, setQuery] = useState('')
  const [hits, setHits] = useState<SearchHit[]>([])
  const [spaces, setSpaces] = useState<KnowledgeSpace[]>([])
  const [promotions, setPromotions] = useState<Promotion[]>([])
  const [dialog, setDialog] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [busyId, setBusyId] = useState<string | null>(null)
  const [spaceBusy, setSpaceBusy] = useState(false)
  const canReview = role === 'reviewer' || role === 'admin'

  const load = useCallback(async () => {
    const [spaceResult, promotionResult] = await Promise.all([
      api.spaces(token),
      api.promotions(token),
    ])
    setSpaces(spaceResult.items)
    setPromotions(promotionResult.items)
  }, [token])

  useEffect(() => {
    void load().catch(() => setError('知识库数据加载失败，请稍后重试。'))
  }, [load])

  const personalSpace = spaces.find((space) => space.kind === 'personal' && space.owner_id === currentUserId) ?? null

  async function search(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError('')
    try {
      setHits(await api.searchKnowledge(token, query))
    } catch {
      setError('知识库搜索未能完成，请稍后重试。')
    }
  }

  async function act(promotion: Promotion, action: () => Promise<Promotion>) {
    setError('')
    setNotice('')
    setBusyId(promotion.id)
    try {
      await action()
      await load()
    } catch (reason) {
      setError(displayError((reason as Partial<ApiError>).code, '晋升操作未能完成。'))
    } finally {
      setBusyId(null)
    }
  }

  async function createPersonalSpace() {
    setError('')
    setNotice('')
    setSpaceBusy(true)
    try {
      await api.createPersonalSpace(token)
      await load()
      setNotice('个人知识库已就绪。')
    } catch (reason) {
      setError(displayError((reason as Partial<ApiError>).code, '个人知识库创建失败。'))
    } finally {
      setSpaceBusy(false)
    }
  }

  async function ingestCurrentVersion() {
    if (!personalSpace || !selectedVersionId) return
    setError('')
    setNotice('')
    setSpaceBusy(true)
    try {
      const result = await api.ingestToSpace(token, personalSpace.id, selectedVersionId)
      setNotice(`版本已收入个人知识库（状态：${displayLabel(zhCN.status, result.state)}），现在可以被检索。`)
    } catch (reason) {
      setError(displayError((reason as Partial<ApiError>).code, '收入个人知识库失败。'))
    } finally {
      setSpaceBusy(false)
    }
  }

  const groupedSpaces = [...spaces].sort((a, b) => (SPACE_ORDER[a.kind] ?? 9) - (SPACE_ORDER[b.kind] ?? 9))

  const versionDisplay = (promotion: Promotion) =>
    promotion.document_title
      ? `《${promotion.document_title}》${promotion.version_number != null ? ` v${promotion.version_number}` : ''}`
      : `版本 ${promotion.version_id.slice(0, 8)}…`

  return <main className="knowledge-workspace">
    <header><p className="eyebrow">知识库</p><h1>搜索与受治理的知识晋升</h1></header>
    {notice && <p className="success" role="status">{notice}</p>}
    <section className="feature-panel">
      <h2>知识空间</h2>
      <p className="muted">个人库仅自己可检索；共享与规范库全员可检索，内容须经晋升治理进入。</p>
      <ul className="space-list">
        {groupedSpaces.map((space) => <li key={space.id} className="space-item">
          <strong>{displayLabel(zhCN.space, space.kind)}</strong>
          <span>{space.kind === 'personal' && space.owner_id === currentUserId ? '我的个人库' : displayLabel(zhCN.space, space.kind) + ' · 全员'}</span>
        </li>)}
      </ul>
      {!personalSpace && <button type="button" onClick={() => void createPersonalSpace()} disabled={spaceBusy}>{spaceBusy ? '创建中…' : '创建个人知识库'}</button>}
      {personalSpace && selectedVersionId && <button type="button" onClick={() => void ingestCurrentVersion()} disabled={spaceBusy}>{spaceBusy ? '处理中…' : selectedVersionLabel ? `将 ${selectedVersionLabel} 收入个人知识库` : '将当前选中版本收入个人知识库'}</button>}
    </section>
    <section className="feature-panel">
      <form className="search-row" onSubmit={search}>
        <input aria-label="知识库搜索" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索已索引来源（如：采购比价、差旅、印章）" />
        <button type="submit" disabled={!query.trim()}>搜索</button>
      </form>
      {error && <p className="error" role="alert">{error}</p>}
      <ul className="search-results">{hits.map((hit, index) => <li key={`${hit.chunk_id}-${index}`}><strong>{hit.title}</strong><span>{hit.heading_path.join(' / ')}</span><q>{hit.quote}</q></li>)}</ul>
      {query && !error && hits.length === 0 && <p className="muted">未找到匹配的已索引来源。</p>}
    </section>
    <section className="feature-panel">
      <h2>晋升申请（共享/规范库）</h2>
      {promotions.length === 0 ? <p className="muted">暂无晋升申请。</p> : promotions.map((promotion) => {
        const space = spaces.find((item) => item.id === promotion.target_space_id)
        return <article className="promotion-row" key={promotion.id}>
          <div className="promotion-head">
            <strong>{displayLabel(zhCN.promotionStatus, promotion.status)}</strong>
            <span>{space ? displayLabel(zhCN.space, space.kind) : ''} · {versionDisplay(promotion)}</span>
          </div>
          <span>{displayLabel(zhCN.qualityStatus, promotion.quality_status)}{promotion.public_authority ? ' · 公开权威' : ''}</span>
          {canReview && <div className="action-row">
            {promotion.status === 'pending_review' && <>
              <button type="button" onClick={() => void act(promotion, () => api.reviewPromotion(token, promotion.id, true))} disabled={busyId === promotion.id}>批准</button>
              <button type="button" onClick={() => void act(promotion, () => api.reviewPromotion(token, promotion.id, false))} disabled={busyId === promotion.id}>驳回</button>
            </>}
            {promotion.status === 'approved' && <button type="button" onClick={() => void act(promotion, () => api.activatePromotion(token, promotion.id))} disabled={busyId === promotion.id}>{busyId === promotion.id ? '索引中…' : '激活索引'}</button>}
            {promotion.status === 'indexed' && <button type="button" onClick={() => void act(promotion, () => api.revokePromotion(token, promotion.id))} disabled={busyId === promotion.id}>撤销</button>}
          </div>}
        </article>
      })}
      {selectedVersionId && <button type="button" onClick={() => setDialog(true)}>{selectedVersionLabel ? `为 ${selectedVersionLabel} 申请晋升` : '为当前版本申请晋升'}</button>}
    </section>
    {dialog && selectedVersionId && <PromotionDialog token={token} versionId={selectedVersionId} versionLabel={selectedVersionLabel} spaces={spaces} onClose={() => setDialog(false)} onCreated={() => { setDialog(false); void load().catch(() => setError('晋升申请创建成功，但列表刷新失败。')) }} />}
  </main>
}
