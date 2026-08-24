import type { ToolTrace as Trace } from '../../api/client'
import { displayLabel, zhCN } from '../../app/strings'

function safeDisplay(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return '[工具数据不可用]'
  }
}

export function ToolTrace({ trace }: { trace: Trace }) {
  return <details className={`tool-trace ${trace.status}`}>
    <summary>工具 · {trace.name} · {displayLabel(zhCN.status, trace.status)}</summary>
    <dl>
      <dt>参数</dt><dd><pre>{safeDisplay(trace.arguments)}</pre></dd>
      {trace.result !== undefined && <><dt>结果</dt><dd><pre>{safeDisplay(trace.result)}</pre></dd></>}
      {trace.error_code && <><dt>原因</dt><dd>{trace.error_code}</dd></>}
    </dl>
  </details>
}
