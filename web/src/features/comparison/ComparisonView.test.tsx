import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { api } from '../../api/client'
import type { Comparison } from '../../api/client'
import { ComparisonView } from './ComparisonView'

vi.mock('../../api/client', () => ({ api: { compare: vi.fn() } }))

const compareMock = vi.mocked(api.compare)

const versions = [
  { id: 'v1', document_id: 'doc', number: 1, content_sha256: 'a', storage_key: 'a', created_by: 'u', created_at: '2026-09-01T00:00:00Z' },
  { id: 'v2', document_id: 'doc', number: 2, content_sha256: 'b', storage_key: 'b', created_by: 'u', created_at: '2026-09-02T00:00:00Z' },
]

function result(overrides: Partial<Comparison>): Comparison {
  return {
    version_a_id: 'v1',
    version_b_id: 'v2',
    comparison_type: 'semantic',
    engine: 'llm',
    degraded: false,
    degraded_reason: null,
    truncated: false,
    changes: [],
    summary: '语义对比完成（模型语义分析），共发现 1 项变化',
    citations: [],
    ...overrides,
  }
}

async function runCompare() {
  const user = userEvent.setup()
  render(<ComparisonView token="token" versions={versions} />)
  await user.click(screen.getByRole('button', { name: '开始对比' }))
  return user
}

describe('ComparisonView', () => {
  it('labels a model-backed comparison and renders semantic change detail', async () => {
    compareMock.mockResolvedValue(result({
      changes: [{
        category: 'semantic_rewrite',
        summary: '补语调整：归档要求表述更完整',
        old_text: '未按规定归档采购合同',
        new_text: '未按规定妥善归档采购合同',
        impact: '意思未变，属于表述调整',
        semantic_equivalent: true,
        version_a_id: 'v1',
        version_b_id: 'v2',
        citations: [],
      }],
    }))

    await runCompare()

    expect(await screen.findByText('语义对比 · 模型')).toBeTruthy()
    expect(screen.getByText('语义等价')).toBeTruthy()
    expect(screen.getByText('旧版原文')).toBeTruthy()
    expect(screen.getByText('未按规定妥善归档采购合同')).toBeTruthy()
    expect(screen.getByText('影响：意思未变，属于表述调整')).toBeTruthy()
  })

  it('shows the offline heuristic engine without implying model analysis', async () => {
    compareMock.mockResolvedValue(result({ engine: 'heuristic', summary: '离线启发式对比完成，共发现 1 项变化' }))

    await runCompare()

    expect(await screen.findByText('本地启发式 · 未接入模型')).toBeTruthy()
    expect(screen.getByText(/不是模型能力/)).toBeTruthy()
  })

  it('explains a degraded fallback to line diff', async () => {
    compareMock.mockResolvedValue(result({
      engine: 'difflib',
      degraded: true,
      degraded_reason: 'provider_not_configured',
      summary: '逐行差异对比完成，共发现 1 项变化',
    }))

    await runCompare()

    expect(await screen.findByText('逐行差异 · 已降级')).toBeTruthy()
    expect(screen.getByRole('status').textContent).toContain('未配置真实模型')
  })

  it('warns when long sources were truncated', async () => {
    compareMock.mockResolvedValue(result({ truncated: true }))

    await runCompare()

    expect((await screen.findByText(/仅对比了开头部分/)).textContent).toContain('结论可能不完整')
  })

  it('reports a failed comparison without inventing a result', async () => {
    compareMock.mockRejectedValue({ code: 'provider_unavailable' })

    await runCompare()

    expect((await screen.findByRole('alert')).textContent).toContain('模型服务暂时不可用')
    expect(screen.queryByText(/对比完成/)).toBeNull()
  })
})
