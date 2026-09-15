import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { displayError, displayLabel, zhCN } from '../../app/strings'
import { api } from '../../api/client'
import type { ApiError, Comparison, ComparisonChange, DocumentVersion } from '../../api/client'

const MODE_LABELS: Record<string, string> = {
  semantic: '语义对比',
  requirements: '要求对比',
  version: '版本对比',
  standards: '标准对比',
  precedent: '先例对比',
}

// 引擎文案必须如实描述结果是怎么来的：离线启发式与降级回退都不得暗示模型参与了分析。
const ENGINE_DETAILS: Record<string, string> = {
  llm: '由真实模型做语义分析，可识别「改写但语义等价」的段落。',
  heuristic: '当前为离线演示模式（本地 FakeProvider）：结果是段落比对 + 相似度判定，不是模型能力。',
  difflib: '未使用语义分析，本次为逐行文本差异。',
}

const DEGRADED_REASONS: Record<string, string> = {
  provider_not_configured: '未配置真实模型（MODEL_PROVIDER=fake）。把 MODEL_PROVIDER 设为 self 并填好 SELF_AI_* 后自动启用语义对比。',
  provider_unavailable: '模型服务暂时不可用（超时或网络错误），已回退为逐行差异，可稍后重试。',
  provider_invalid_response: '模型返回的结果无法解析，已回退为逐行差异。',
  provider_offline: '当前为离线演示模型，本功能需要真实模型。',
}

function engineTone(engine: string) {
  if (engine === 'llm') return 'model'
  if (engine === 'difflib') return 'degraded'
  return 'offline'
}

function ChangeCard({ change }: { change: ComparisonChange }) {
  return <article className="comparison-change">
    <header className="comparison-change-head">
      <span className={`change-badge change-${change.category}`}>{displayLabel(zhCN.comparisonCategory, change.category)}</span>
      {change.semantic_equivalent === true && <span className="change-chip">语义等价</span>}
      {change.semantic_equivalent === false && ['modification', 'semantic_rewrite', 'tone_change'].includes(change.category)
        && <span className="change-chip change-chip-warn">语义已变</span>}
    </header>
    <p className="change-summary">{change.summary}</p>
    {change.impact && <p className="change-impact">影响：{change.impact}</p>}
    {(change.old_text || change.new_text) && <div className="change-fragments">
      {change.old_text && <div className="change-fragment change-fragment-old">
        <span>旧版原文</span>
        <pre>{change.old_text}</pre>
      </div>}
      {change.new_text && <div className="change-fragment change-fragment-new">
        <span>新版原文</span>
        <pre>{change.new_text}</pre>
      </div>}
    </div>}
  </article>
}

type StoredComparison = { v: 1; a: string; b: string; mode: string; result: Comparison }

function readStored(docKey: string): StoredComparison | null {
  try {
    const raw = sessionStorage.getItem(docKey)
    if (!raw) return null
    const parsed = JSON.parse(raw) as Partial<StoredComparison>
    if (parsed.v !== 1 || typeof parsed.a !== 'string' || typeof parsed.b !== 'string'
      || typeof parsed.mode !== 'string' || !parsed.result || typeof parsed.result !== 'object') return null
    return parsed as StoredComparison
  } catch { return null }
}

function writeStored(docKey: string, value: StoredComparison | null) {
  try {
    if (value) sessionStorage.setItem(docKey, JSON.stringify(value))
    else sessionStorage.removeItem(docKey)
  } catch { /* 存储不可用时仅丢失跨 tab 保持，不影响本次对比 */ }
}

export function ComparisonView({ token, documentId, versions }: { token: string; documentId: string; versions: DocumentVersion[] }) {
  const [a, setA] = useState('')
  const [b, setB] = useState('')
  const [mode, setMode] = useState('semantic')
  const [result, setResult] = useState<Comparison | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const restored = useRef(false)
  const docKey = `doc-agent-compare-${documentId}`

  // 版本列表加载后默认选中最早与最新版本；有上次对比记录时优先还原（切换 tab 不丢结果）
  useEffect(() => {
    if (versions.length < 2 || a || b) return
    if (!restored.current) {
      restored.current = true
      const saved = readStored(docKey)
      const known = (id: string) => versions.some((version) => version.id === id)
      if (saved && saved.a !== saved.b && known(saved.a) && known(saved.b)) {
        setA(saved.a)
        setB(saved.b)
        setMode(saved.mode)
        setResult(saved.result)
        return
      }
    }
    setA((current) => current || versions[0].id)
    setB((current) => current || versions[versions.length - 1].id)
  }, [versions, a, b, docKey])

  // 选择变化即收起旧结果：旧结果与新选择不再对应，避免显示空变更卡片引起误读
  function selectA(next: string) {
    setA(next); setResult(null); setError(''); writeStored(docKey, null)
  }
  function selectB(next: string) {
    setB(next); setResult(null); setError(''); writeStored(docKey, null)
  }
  function selectMode(next: string) {
    setMode(next); setResult(null); setError(''); writeStored(docKey, null)
  }

  async function compare(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError('')
    setResult(null)
    if (!a || !b || a === b) {
      setError('请选择两个不同的不可变版本。')
      return
    }
    setBusy(true)
    try {
      const next = await api.compare(token, a, b, mode)
      if (next.version_a_id !== a || next.version_b_id !== b) {
        setError('对比结果与所选版本不匹配，请重试。')
        return
      }
      setResult(next)
      writeStored(docKey, { v: 1, a, b, mode, result: next })
    } catch (reason) {
      setError(displayError((reason as Partial<ApiError>).code, '版本对比未能完成，请稍后重试。'))
    } finally {
      setBusy(false)
    }
  }

  if (versions.length < 2) {
    return <section className="feature-panel">
      <p className="eyebrow">版本对比</p>
      <h2>对比不可变版本</h2>
      <p className="muted">当前文档只有 {versions.length} 个版本。对比需要至少两个版本——请在左侧"新建文档"上传修订稿，或让作者针对评审意见提交新版本后，再回到此页对比。</p>
    </section>
  }

  const label = (version: DocumentVersion) => `v${version.number}（${new Date(version.created_at).toLocaleDateString('zh-CN')}）`
  const visibleChanges = result ? result.changes.filter((change) => change.version_a_id === a && change.version_b_id === b) : []

  return <section className="feature-panel">
    <p className="eyebrow">版本对比</p>
    <h2>对比不可变版本</h2>
    <form className="compare-form" onSubmit={compare}>
      <div className="form-row">
        <label>版本 A<select value={a} onChange={(event) => selectA(event.target.value)}>
          {versions.map((version) => <option key={version.id} value={version.id}>{label(version)}</option>)}
        </select></label>
        <label>版本 B<select value={b} onChange={(event) => selectB(event.target.value)}>
          {versions.map((version) => <option key={version.id} value={version.id}>{label(version)}</option>)}
        </select></label>
        <label>对比方式<select value={mode} onChange={(event) => selectMode(event.target.value)}>
          {Object.entries(MODE_LABELS).map(([value, text]) => <option key={value} value={value}>{text}</option>)}
        </select></label>
      </div>
      <button type="submit" disabled={!a || !b || a === b || busy}>{busy ? '对比中…' : '开始对比'}</button>
    </form>
    {error && <p className="error" role="alert">{error}</p>}
    {result && <div className="comparison-result">
      <div className="comparison-headline">
        <strong>{result.summary}</strong>
        <span className={`engine-badge engine-${engineTone(result.engine)}`}>
          {displayLabel(zhCN.comparisonEngine, result.engine)}
        </span>
      </div>
      <p className="comparison-engine-note">{ENGINE_DETAILS[result.engine] ?? ''}</p>
      {result.degraded && <p className="comparison-warning" role="status">
        {DEGRADED_REASONS[result.degraded_reason ?? ''] ?? '语义对比未能完成，已回退为逐行差异。'}
      </p>}
      {result.truncated && <p className="comparison-warning" role="status">
        正文较长，仅对比了开头部分，结论可能不完整。
      </p>}
      <div className="comparison-changes">
        {visibleChanges.map((change, index) => <ChangeCard key={`${change.category}-${index}`} change={change} />)}
      </div>
    </div>}
  </section>
}
