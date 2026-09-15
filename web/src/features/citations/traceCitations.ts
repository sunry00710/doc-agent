import type { Citation, ToolTrace } from '../../api/client'

// 后端 /api/chat 目前不返回顶层 citations，检索命中藏在
// traces[].result.hits 里（字段与 Citation 同构）。
// 这里做一次投影，让「引用」面板在有检索命中时能真的显示来源。
export function citationsFromTraces(traces: ToolTrace[] | undefined): Citation[] {
  if (!traces?.length) return []
  const seen = new Set<string>()
  const citations: Citation[] = []
  for (const trace of traces) {
    if (trace.name !== 'search_knowledge' || trace.status !== 'succeeded') continue
    const hits = (trace.result as { hits?: unknown } | undefined)?.hits
    if (!Array.isArray(hits)) continue
    for (const raw of hits) {
      const hit = raw as Partial<Citation>
      if (
        typeof hit.chunk_id !== 'string' ||
        typeof hit.title !== 'string' ||
        typeof hit.quote !== 'string' ||
        seen.has(hit.chunk_id)
      ) {
        continue
      }
      seen.add(hit.chunk_id)
      citations.push({
        chunk_id: hit.chunk_id,
        document_id: hit.document_id ?? '',
        version_id: hit.version_id ?? '',
        title: hit.title,
        heading_path: Array.isArray(hit.heading_path) ? hit.heading_path : [],
        quote: hit.quote,
        start_offset: hit.start_offset ?? 0,
        end_offset: hit.end_offset ?? 0,
      })
    }
  }
  return citations.slice(0, 20)
}
