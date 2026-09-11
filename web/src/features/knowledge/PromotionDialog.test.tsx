import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { api } from '../../api/client'
import { PromotionDialog } from './PromotionDialog'

vi.mock('../../api/client', async (importOriginal) => {
  const original = await importOriginal<typeof import('../../api/client')>()
  return {
    ...original,
    api: {
      ...original.api,
      createPromotion: vi.fn(),
    },
  }
})

describe('PromotionDialog', () => {
  beforeEach(() => {
    vi.mocked(api.createPromotion).mockReset()
  })

  it('sends only the source version and target space', async () => {
    const user = userEvent.setup()
    const onCreated = vi.fn()
    vi.mocked(api.createPromotion).mockResolvedValue({
      id: 'promotion-1',
      version_id: 'version-1',
      target_space_id: 'space-1',
      requested_by: 'user-1',
      reviewed_by: null,
      status: 'pending_review',
      quality_status: 'passed',
      findings: [],
      policy_version: 'quality-gate-v1',
      authority_level: 0,
      public_authority: false,
    })

    render(
      <PromotionDialog
        token="token"
        versionId="version-1"
        spaces={[
          {
            id: 'space-1',
            kind: 'shared',
            owner_id: null,
            project_id: null,
          },
        ]}
        onClose={() => undefined}
        onCreated={onCreated}
      />,
    )

    await user.selectOptions(
      screen.getByLabelText('目标知识空间'),
      'space-1',
    )
    await user.click(
      screen.getByRole('button', { name: '确认申请' }),
    )

    expect(api.createPromotion).toHaveBeenCalledWith(
      'token',
      {
        version_id: 'version-1',
        target_space_id: 'space-1',
      },
    )
    expect(onCreated).toHaveBeenCalledOnce()
  })

  it('shows structured blocking findings returned by the quality gate', async () => {
    const user = userEvent.setup()
    vi.mocked(api.createPromotion).mockRejectedValue({
      code: 'validation_error', message: 'Promotion is blocked by quality gate', request_id: 'request-1', retryable: false,
      details: { findings: [{ category: 'contract_requirement', summary: '必须包含风险分析', evidence: '未找到匹配内容', requirement_id: 'req-risk', severity: 'high', mandatory: true, blocking: true, human_review_required: false }] },
    })
    render(<PromotionDialog token="token" versionId="version-1" spaces={[{ id: 'space-1', kind: 'shared', owner_id: null, project_id: null }]} onClose={() => undefined} onCreated={() => undefined} />)
    await user.selectOptions(screen.getByLabelText('目标知识空间'), 'space-1')
    await user.click(screen.getByRole('button', { name: '确认申请' }))
    expect(screen.getByText('提交的数据无效，请检查后重试。')).toBeTruthy()
    expect(screen.getByText('阻断')).toBeTruthy()
    expect(screen.getByText('要求：req-risk')).toBeTruthy()
    expect(screen.getByText('必须包含风险分析')).toBeTruthy()
    expect(screen.getByText('证据：未找到匹配内容')).toBeTruthy()
  })

  it('shows human review labels for non-blocking findings', async () => {
    const user = userEvent.setup()
    vi.mocked(api.createPromotion).mockRejectedValue({
      code: 'validation_error', message: 'Promotion needs review', request_id: 'request-2', retryable: false,
      details: { findings: [{ category: 'contract_unconfirmed', summary: '写作契约尚未完成评审确认', evidence: '', requirement_id: null, severity: 'medium', mandatory: false, blocking: false, human_review_required: true }] },
    })
    render(<PromotionDialog token="token" versionId="version-1" spaces={[{ id: 'space-1', kind: 'shared', owner_id: null, project_id: null }]} onClose={() => undefined} onCreated={() => undefined} />)
    await user.selectOptions(screen.getByLabelText('目标知识空间'), 'space-1')
    await user.click(screen.getByRole('button', { name: '确认申请' }))
    expect(screen.getByText('需人工复核')).toBeTruthy()
    expect(screen.getByText('契约状态')).toBeTruthy()
    expect(screen.getByText('写作契约尚未完成评审确认')).toBeTruthy()
  })
})
