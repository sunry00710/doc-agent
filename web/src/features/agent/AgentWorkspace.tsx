import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import type { ChatResponse, Citation, ToolTrace as Trace } from '../../api/client'
import { ToolTrace } from './ToolTrace'

type Message = { id: string; role: 'user' | 'assistant'; text: string; traces?: Trace[] }

export type AgentContext = {
  projectName: string
  documentTitle: string | null
  versionLabel: string | null
}

export type KnowledgeSource = {
  id: string
  label: string
  kind: string
}

export type TargetDocument = {
  id: string
  title: string
}

type AgentWorkspaceProps = {
  onSend: (text: string, options: { confirmed: boolean; idempotencyKey?: string }) => Promise<ChatResponse>
  onCitations: (citations: Citation[]) => void
  context?: AgentContext
  sessionKey?: string
  userId?: string
  onApplySuggestion?: (text: string) => void
  compact?: boolean
  knowledgeSources?: KnowledgeSource[]
  selectedSourceIds?: string[]
  onToggleSource?: (id: string) => void
  // 工作台自足：就地选择目标文档，无需跳转文档页
  targetDocuments?: TargetDocument[]
  activeDocumentId?: string | null
  onSelectTarget?: (documentId: string) => void
}

function messageStorageKey(sessionKey?: string, userId?: string) {
  const scope = userId ?? 'anonymous'
  return sessionKey ? `doc-agent-messages-${scope}-${sessionKey}` : `doc-agent-messages-${scope}`
}

function mayMutate(text: string): boolean {
  return /\b(submit|promote|promotion|archive|revoke|approve|reject)\b|提交|发布|晋升|归档|撤销|批准|驳回/i.test(text)
}

export function AgentWorkspace({ onSend, onCitations, context, sessionKey, userId, onApplySuggestion, compact = false, knowledgeSources, selectedSourceIds, onToggleSource, targetDocuments, activeDocumentId, onSelectTarget }: AgentWorkspaceProps) {
  const [text, setText] = useState('')
  const [messages, setMessages] = useState<Message[]>(() => {
    try {
      const stored = sessionStorage.getItem(messageStorageKey(sessionKey, userId))
      return stored ? JSON.parse(stored) as Message[] : []
    } catch {
      return []
    }
  })
  const [sending, setSending] = useState(false)
  const [needsConfirmation, setNeedsConfirmation] = useState(false)
  const [error, setError] = useState('')
  const [showGuide, setShowGuide] = useState(() => sessionStorage.getItem('doc-agent-guide-closed') !== 'true')

  useEffect(() => {
    try {
      const stored = sessionStorage.getItem(messageStorageKey(sessionKey, userId))
      setMessages(stored ? JSON.parse(stored) as Message[] : [])
    } catch {
      setMessages([])
    }
  }, [sessionKey, userId])

  useEffect(() => {
    sessionStorage.setItem(messageStorageKey(sessionKey, userId), JSON.stringify(messages))
  }, [messages, sessionKey, userId])

  async function send(confirmed = false) {
    const content = text.trim()
    if (!content || sending) return
    if (mayMutate(content) && !confirmed) {
      setNeedsConfirmation(true)
      return
    }
    setNeedsConfirmation(false)
    setError('')
    setSending(true)
    setMessages((current) => [...current, { id: crypto.randomUUID(), role: 'user', text: content }])
    setText('')
    try {
      const response = await onSend(content, { confirmed, idempotencyKey: confirmed ? crypto.randomUUID() : undefined })
      setMessages((current) => [...current, { id: crypto.randomUUID(), role: 'assistant', text: response.text, traces: response.traces }])
      onCitations(response.citations ?? [])
    } catch {
      setError('Agent 请求未能完成，请稍后重试。')
      setText(content)
    } finally {
      setSending(false)
    }
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    void send()
  }

  const contextLabel = context
    ? [context.projectName, context.documentTitle ? `${context.documentTitle}${context.versionLabel ? `（${context.versionLabel}）` : ''}` : null].filter(Boolean).join(' · ')
    : ''

  return <main className={compact ? 'conversation conversation-compact' : 'conversation'}>
    <header className="conversation-header"><div><p className="eyebrow">Agent 工作台</p><h1>基于证据处理文档</h1></div><span className="status-dot">就绪</span></header>
    {targetDocuments && onSelectTarget && (
      <label className="target-document-select">目标文档（让 Agent 处理的对象）
        <select value={activeDocumentId ?? ''} onChange={(event) => onSelectTarget(event.target.value)}>
          <option value="">仅知识库检索（不绑定文档）</option>
          {targetDocuments.map((item) => <option key={item.id} value={item.id}>{item.title}</option>)}
        </select>
      </label>
    )}
    <div className="context-banner" aria-label="Agent 上下文">
      {context && context.documentTitle && context.versionLabel
        ? <><strong>已绑定上下文</strong><span>{contextLabel}——Agent 将基于该版本内容回答。</span></>
        : context && context.projectName
          ? <><strong>上下文不完整</strong><span>当前项目：{context.projectName}。尚未选择文档版本，Agent 仅能检索知识库。</span></>
          : <><strong>未绑定上下文</strong><span>请先在左侧选择项目，Agent 才能访问项目内容。</span></>}
    </div>
    {knowledgeSources && knowledgeSources.length > 0 && onToggleSource && (
      <fieldset className="knowledge-sources" aria-label="知识检索来源">
        <legend>知识检索来源（可多选）</legend>
        <div className="knowledge-source-chips">
          {knowledgeSources.map((source) => {
            const active = selectedSourceIds?.includes(source.id) ?? false
            return <label key={source.id} className={active ? 'source-chip active' : 'source-chip'}>
              <input type="checkbox" checked={active} onChange={() => onToggleSource(source.id)} />
              {source.label}
            </label>
          })}
        </div>
        <p className="muted">{selectedSourceIds && selectedSourceIds.length > 0 ? `检索范围：${selectedSourceIds.length} 个知识库` : '未选中任何库时，检索你全部授权范围（含未晋升的个人草稿）。'}</p>
      </fieldset>
    )}
    {showGuide && <section className="feature-panel" aria-label="使用指引"><div className="conversation-header"><div><h2>快速开始</h2><p className="muted">选择项目和文档后，可让 Agent 检查内容、对比版本或检索证据。</p></div><button type="button" onClick={() => { sessionStorage.setItem('doc-agent-guide-closed', 'true'); setShowGuide(false) }}>关闭指引</button></div><ol><li>在左侧选择项目，并在“文档”中选择版本。</li><li>确认上方上下文已绑定项目与文档版本。</li><li>在下方输入你的问题或请求。</li><li>提交、晋升、归档等会改变状态的操作需要再次确认。</li></ol></section>}
    <section className="messages" aria-live="polite">
      {messages.length === 0 && <div className="empty-state"><h2>从问题或请求开始</h2><p>可请求检查、版本对比或基于证据的建议。涉及文档或知识状态变更的操作需要确认。</p></div>}
      {messages.map((message) => <article className={`message ${message.role}`} key={message.id}><p className="message-role">{message.role === 'user' ? '我' : 'Agent'}</p><p>{message.text}</p>{message.role === 'assistant' && onApplySuggestion && <button type="button" className="apply-suggestion" onClick={() => onApplySuggestion(message.text)}>应用到草稿</button>}{message.traces?.map((trace) => <ToolTrace key={trace.tool_call_id} trace={trace} />)}</article>)}
    </section>
    {error && <p className="error" role="alert">{error}</p>}
    {needsConfirmation && <section className="confirmation" role="dialog" aria-label="确认操作"><strong>确认执行操作</strong><p>该请求可能会变更文档或知识状态。请确认你希望授权此操作。</p><div><button type="button" onClick={() => setNeedsConfirmation(false)}>取消</button><button type="button" onClick={() => void send(true)}>确认并发送</button></div></section>}
    <form className="composer" onSubmit={submit}><label htmlFor="agent-message">消息</label><textarea id="agent-message" value={text} onChange={(event) => setText(event.target.value)} placeholder="让 Agent 检查、对比或分析文档…" rows={3} disabled={sending} /><button type="submit" disabled={sending || !text.trim()}>{sending ? '处理中…' : '发送'}</button></form>
  </main>
}
