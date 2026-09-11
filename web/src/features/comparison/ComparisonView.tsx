import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { displayError, displayLabel, zhCN } from '../../app/strings'
import { api } from '../../api/client'
import type { ApiError, DocumentVersion } from '../../api/client'

const MODE_LABELS: Record<string, string> = {
  semantic: '语义对比',
  requirements: '要求对比',
}

export function ComparisonView({ token, versions }: { token: string; versions: DocumentVersion[] }) {
  const [a, setA] = useState('')
  const [b, setB] = useState('')
  const [mode, setMode] = useState('semantic')
  const [result, setResult] = useState<{ version_a_id: string; version_b_id: string; summary: string; changes: { version_a_id: string; version_b_id: string; summary: string; category: string }[] } | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  // 版本列表加载后默认选中最早与最新版本，避免每次手动选择
  useEffect(() => {
    if (versions.length >= 2 && !a && !b) {
      setA(versions[0].id)
      setB(versions[versions.length - 1].id)
    }
  }, [versions, a, b])

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

  return <section className="feature-panel">
    <p className="eyebrow">版本对比</p>
    <h2>对比不可变版本</h2>
    <form className="compare-form" onSubmit={compare}>
      <div className="form-row">
        <label>版本 A<select value={a} onChange={(event) => setA(event.target.value)}>
          {versions.map((version) => <option key={version.id} value={version.id}>{label(version)}</option>)}
        </select></label>
        <label>版本 B<select value={b} onChange={(event) => setB(event.target.value)}>
          {versions.map((version) => <option key={version.id} value={version.id}>{label(version)}</option>)}
        </select></label>
        <label>对比方式<select value={mode} onChange={(event) => setMode(event.target.value)}>
          <option value="semantic">语义对比</option>
          <option value="requirements">要求对比</option>
        </select></label>
      </div>
      <button type="submit" disabled={!a || !b || a === b || busy}>{busy ? '对比中…' : '开始对比'}</button>
    </form>
    {error && <p className="error" role="alert">{error}</p>}
    {result && <article className="comparison-result">
      <strong>{result.summary}</strong>
      {result.changes.filter((change) => change.version_a_id === a && change.version_b_id === b).map((change, index) => <p key={index}><b>{displayLabel(zhCN.comparisonCategory, change.category)}</b> {change.summary}</p>)}
    </article>}
  </section>
}
