import { useState } from 'react'
import type { FormEvent } from 'react'
import type { ChatResponse, Citation, ToolTrace as Trace } from '../../api/client'
import { ToolTrace } from './ToolTrace'

type Message = { id: string; role: 'user' | 'assistant'; text: string; traces?: Trace[] }

type AgentWorkspaceProps = {
  onSend: (text: string, options: { confirmed: boolean; idempotencyKey?: string }) => Promise<ChatResponse>
  onCitations: (citations: Citation[]) => void
}

function mayMutate(text: string): boolean {
  return /\b(submit|promote|promotion|archive|revoke|approve|reject)\b/i.test(text)
}

export function AgentWorkspace({ onSend, onCitations }: AgentWorkspaceProps) {
  const [text, setText] = useState('')
  const [messages, setMessages] = useState<Message[]>([])
  const [sending, setSending] = useState(false)
  const [needsConfirmation, setNeedsConfirmation] = useState(false)
  const [error, setError] = useState('')

  async function send(confirmed = false) {
    const content = text.trim()
    if (!content || sending) return
    if (mayMutate(content) && !confirmed) { setNeedsConfirmation(true); return }
    setNeedsConfirmation(false)
    setError('')
    setSending(true)
    setMessages((current) => [...current, { id: crypto.randomUUID(), role: 'user', text: content }])
    setText('')
    try {
      const response = await onSend(content, { confirmed, idempotencyKey: confirmed ? crypto.randomUUID() : undefined })
      setMessages((current) => [...current, { id: crypto.randomUUID(), role: 'assistant', text: response.text, traces: response.traces }])
      onCitations(response.citations ?? [])
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'The Agent request could not be completed.')
      setText(content)
    } finally { setSending(false) }
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    void send()
  }

  return <main className="conversation">
    <header className="conversation-header"><div><p className="eyebrow">Agent workspace</p><h1>Work through a document with evidence</h1></div><span className="status-dot">Ready</span></header>
    <section className="messages" aria-live="polite">
      {messages.length === 0 && <div className="empty-state"><h2>Start with a question or request</h2><p>Ask for a check, comparison, or evidence-backed suggestion. Actions that change documents or knowledge require confirmation.</p></div>}
      {messages.map((message) => <article className={`message ${message.role}`} key={message.id}><p className="message-role">{message.role === 'user' ? 'You' : 'Agent'}</p><p>{message.text}</p>{message.traces?.map((trace) => <ToolTrace key={trace.tool_call_id} trace={trace} />)}</article>)}
    </section>
    {error && <p className="error" role="alert">{error}</p>}
    {needsConfirmation && <section className="confirmation" role="dialog" aria-label="Confirm action"><strong>Confirm requested action</strong><p>This request may change document or knowledge state. Continue only if you intend to authorize it.</p><div><button type="button" onClick={() => setNeedsConfirmation(false)}>Cancel</button><button type="button" onClick={() => void send(true)}>Confirm and send</button></div></section>}
    <form className="composer" onSubmit={submit}><label htmlFor="agent-message">Message</label><textarea id="agent-message" value={text} onChange={(event) => setText(event.target.value)} placeholder="Ask the Agent to assess a document…" rows={3} disabled={sending} /><button type="submit" disabled={sending || !text.trim()}>{sending ? 'Working…' : 'Send'}</button></form>
  </main>
}
