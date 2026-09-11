import type { Citation } from '../../api/client'

export function CitationPanel({ citations, onOpenCitation }: { citations: Citation[]; onOpenCitation: (citation: Citation) => void }) {
  return <aside className="context-panel" aria-label="引用与上下文">
    <div className="panel-heading"><p className="eyebrow">上下文</p><h2>引用</h2></div>
    {citations.length === 0 ? <p className="muted">Agent 使用的来源会显示在这里。</p> : <ol className="citation-list">
      {citations.map((citation) => <li key={citation.chunk_id}>
        <button type="button" className="citation" aria-label={`打开引用 ${citation.title}`} onClick={() => onOpenCitation(citation)}>
          <strong>{citation.title}</strong><span>{citation.heading_path.join(' / ') || '文档摘录'}</span><q>{citation.quote}</q>
        </button>
      </li>)}
    </ol>}
  </aside>
}
