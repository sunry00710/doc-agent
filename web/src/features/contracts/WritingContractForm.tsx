import { useEffect, useState } from 'react'
import { displayError } from '../../app/strings'
import { api } from '../../api/client'
import type { ApiError, Contract, Requirement, SupervisorSimulation } from '../../api/client'

type FormData = Omit<Contract['revision'], 'revision' | 'reviewer_confirmed'>

const blank = (documentType = ''): FormData => ({ domain: '', document_type: documentType, subject_organization: '', reporting_period: '', purpose: '', audience: '', requirements: [] as Requirement[], standard_ids: [] as string[], precedent_ids: [] as string[], reviewer_id: null as string | null })

const FIELD_LABELS: Record<string, string> = {
  domain: '领域',
  document_type: '文档类型',
  subject_organization: '主体机构',
  reporting_period: '报告期',
  purpose: '写作目的',
  audience: '目标读者',
}

const ASSESSMENT_LABELS: Record<string, string> = {
  satisfied: '已满足',
  unsatisfied: '未满足',
  unknown: '无法判定',
}

export function WritingContractForm({ token, documentId, documentType, canConfirm, source }: { token: string; documentId: string; documentType: string; canConfirm: boolean; source: string }) {
  const [contract, setContract] = useState<Contract | null>(null)
  const [form, setForm] = useState<FormData>(blank(documentType))
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)
  const [simulation, setSimulation] = useState<SupervisorSimulation | null>(null)
  const [simulating, setSimulating] = useState(false)

  useEffect(() => {
    setContract(null)
    setForm(blank(documentType))
    setSimulation(null)
    setError('')
    setNotice('')
    void api.contract(token, documentId).then((next) => {
      setContract(next)
      const { revision: _revision, reviewer_confirmed: _confirmed, ...rest } = next.revision
      setForm(rest)
    }).catch((reason) => {
      const code = (reason as Partial<ApiError>).code
      if (code !== 'not_found') setError(displayError(code, '写作契约加载失败。'))
    })
  }, [documentId, documentType, token])

  function update(field: keyof FormData, value: string) {
    setForm((current) => ({ ...current, [field]: value }))
  }

  function updateRequirement(index: number, patch: Partial<Requirement>) {
    setForm((current) => {
      const requirements = current.requirements.map((item, position) => position === index ? { ...item, ...patch } : item)
      return { ...current, requirements }
    })
    setSimulation(null)
  }

  function addRequirement() {
    setForm((current) => ({ ...current, requirements: [...current.requirements, { id: `req-${current.requirements.length + 1}-${Date.now().toString(36)}`, text: '', mandatory: true }] }))
    setSimulation(null)
  }

  function removeRequirement(index: number) {
    setForm((current) => ({ ...current, requirements: current.requirements.filter((_, position) => position !== index) }))
    setSimulation(null)
  }

  async function save() {
    if (busy) return
    setError('')
    setNotice('')
    const requirements = form.requirements.filter((item) => item.text.trim())
    if (requirements.length === 0) {
      setError('请至少填写一条写作要求（如“须包含审计范围章节”）。')
      return
    }
    setBusy(true)
    try {
      const payload = { ...form, requirements }
      const next = contract ? await api.reviseContract(token, contract.id, payload) : await api.createContract(token, documentId, payload)
      setContract(next)
      setNotice(`契约已保存（修订版 ${next.active_revision}）。`)
      setSimulation(null)
    } catch (reason) {
      setError(displayError((reason as Partial<ApiError>).code, '写作契约保存失败。'))
    } finally {
      setBusy(false)
    }
  }

  async function confirmRevision() {
    if (!contract || busy) return
    setError('')
    setNotice('')
    setBusy(true)
    try {
      const next = await api.confirmContract(token, contract.id)
      setContract(next)
      setNotice('契约修订已由评审确认。')
    } catch (reason) {
      setError(displayError((reason as Partial<ApiError>).code, '契约确认失败。'))
    } finally {
      setBusy(false)
    }
  }

  async function simulate() {
    if (!contract || simulating) return
    setError('')
    setSimulating(true)
    try {
      setSimulation(await api.simulateContract(token, contract.id, source))
    } catch (reason) {
      setError(displayError((reason as Partial<ApiError>).code, '模拟主管评审未能完成。'))
    } finally {
      setSimulating(false)
    }
  }

  return <section className="feature-panel contract-panel">
    <p className="eyebrow">写作契约</p>
    <h2>{contract ? `修订版 ${contract.active_revision}${contract.revision.reviewer_confirmed ? ' · 已确认' : ' · 待确认'}` : '创建写作契约'}</h2>
    <p className="muted">写作要求分为两类：必需满足项未满足会阻断质量门；建议补充项不会阻断提交，但会作为评审关注点。</p>
    <div className="contract-fields">
      {(['domain', 'document_type', 'subject_organization', 'reporting_period', 'purpose', 'audience'] as const).map((field) => (
        <label key={field}>{FIELD_LABELS[field]}<input value={String(form[field])} onChange={(event) => update(field, event.target.value)} /></label>
      ))}
    </div>
    <div className="requirement-editor">
      <h3>写作要求（逐条核对）</h3>
      <p className="muted">必需满足项会阻断质量门；建议补充项不会阻断提交。</p>
      {form.requirements.length === 0 && <p className="muted">尚未添加要求。示例：“审计范围”“采购比价”“整改责任清单”。</p>}
      {form.requirements.map((requirement, index) => <div className="requirement-row" key={requirement.id}>
        <input aria-label={`要求 ${index + 1} 内容`} value={requirement.text} placeholder="要求内容（须在正文中出现的表述）" onChange={(event) => updateRequirement(index, { text: event.target.value })} />
        <label className="mandatory-toggle"><input type="checkbox" checked={requirement.mandatory} onChange={(event) => updateRequirement(index, { mandatory: event.target.checked })} />{requirement.mandatory ? '必需满足' : '建议补充'}</label>
        <button type="button" className="remove-requirement" onClick={() => removeRequirement(index)} aria-label={`删除要求 ${index + 1}`}>删除</button>
      </div>)}
      <button type="button" onClick={addRequirement}>添加要求</button>
    </div>
    <div className="action-row">
      <button type="button" onClick={() => void save()} disabled={busy}>{busy ? '保存中…' : contract ? '保存新修订' : '创建契约'}</button>
      {canConfirm && contract && !contract.revision.reviewer_confirmed && <button type="button" onClick={() => void confirmRevision()} disabled={busy}>确认当前修订</button>}
    </div>
    <div className="simulate-section">
      <h3>模拟主管评审</h3>
      <p className="muted">对当前选中版本的正文运行逐条要求核对，未满足项将列为作者待办。</p>
      <button type="button" onClick={() => void simulate()} disabled={!contract || !source || simulating}>
        {!contract ? '请先保存契约' : !source ? '请先选择版本' : simulating ? '模拟中…' : '运行模拟主管评审'}
      </button>
        {simulation && <div className="simulation-result">
          <p><strong>要求核对（{simulation.assessments.filter((item) => item.status === 'satisfied').length}/{simulation.assessments.length} 已满足）：</strong></p>
        <ul className="assessment-list">
          {simulation.assessments.map((assessment) => <li key={assessment.requirement_id} className={`assessment ${assessment.status}`}>
            <span className="assessment-status">{assessment.blocking ? '必需' : '建议'}</span><span className={`assessment-status assessment-result-${assessment.status}`}>{ASSESSMENT_LABELS[assessment.status] ?? assessment.status}</span>
            <span className="assessment-text">{form.requirements.find((item) => item.id === assessment.requirement_id)?.text ?? assessment.requirement_id}</span>
          </li>)}
        </ul>
        {simulation.concerns.length > 0
          ? <>
              <p><strong>主管关注点（{simulation.concerns.length} 项，其中 {simulation.concerns.filter((concern) => concern.blocking).length} 项阻断质量门）：</strong></p>
              <ul className="concern-list">{simulation.concerns.map((concern) => <li key={concern.id} className={concern.blocking ? 'blocking' : 'advisory'}><strong>{concern.blocking ? '必需满足' : '建议补充'}</strong> {concern.summary}</li>)}</ul>
            </>
          : <p className="success">所有要求均已满足，可以提交评审。</p>}
      </div>}
    </div>
    {notice && <p className="success" role="status">{notice}</p>}
    {error && <p className="error" role="alert">{error}</p>}
  </section>
}
