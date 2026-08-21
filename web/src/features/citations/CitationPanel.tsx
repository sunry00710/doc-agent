import type { Citation } from '../../api/client'

export function CitationPanel({ citations }: { citations: Citation[] }) {
  return <aside className="context-panel" aria-label="Citations and context">
    <div className="panel-heading"><p className="eyebrow">Context</p><h2>Citations</h2></div>
    {citations.length === 0 ? <p className="muted">Sources used by the Agent will appear here.</p> : <ol className="citation-list">
      {citations.map((citation) => <li key={citation.chunk_id}>
        <button type="button" className="citation" aria-label={`Open citation ${citation.title}`} onClick={() => window.alert(`${citation.title}\n\n${citation.quote}`)}>
          <strong>{citation.title}</strong><span>{citation.heading_path.join(' / ') || 'Document excerpt'}</span><q>{citation.quote}</q>
        </button>
      </li>)}
    </ol>}
  </aside>
}
