import type { ToolTrace as Trace } from '../../api/client'

function safeDisplay(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return '[Unavailable tool data]'
  }
}

export function ToolTrace({ trace }: { trace: Trace }) {
  return <details className={`tool-trace ${trace.status}`}>
    <summary>Tool · {trace.name} · {trace.status}</summary>
    <dl>
      <dt>Arguments</dt><dd><pre>{safeDisplay(trace.arguments)}</pre></dd>
      {trace.result !== undefined && <><dt>Result</dt><dd><pre>{safeDisplay(trace.result)}</pre></dd></>}
      {trace.error_code && <><dt>Reason</dt><dd>{trace.error_code}</dd></>}
    </dl>
  </details>
}
