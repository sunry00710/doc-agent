import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const contractMock = vi.fn()
const createContractMock = vi.fn()
const reviseContractMock = vi.fn()
const confirmContractMock = vi.fn()
const simulateContractMock = vi.fn()

vi.mock('../../api/client', () => ({
  api: {
    contract: (...args: unknown[]) => contractMock(...args),
    createContract: (...args: unknown[]) => createContractMock(...args),
    reviseContract: (...args: unknown[]) => reviseContractMock(...args),
    confirmContract: (...args: unknown[]) => confirmContractMock(...args),
    simulateContract: (...args: unknown[]) => simulateContractMock(...args),
  },
}))

import { WritingContractForm } from './WritingContractForm'

const savedContract = {
  id: 'contract-1',
  project_id: 'p1',
  document_id: 'd1',
  active_revision: 1,
  revision: {
    domain: '审计', document_type: '报告', subject_organization: '演示单位', reporting_period: '2026 上半年',
    purpose: '汇报', audience: '管理层',
    requirements: [{ id: 'scope-section', text: '审计范围', mandatory: true }, { id: 'owner-list', text: '整改责任清单', mandatory: true }],
    standard_ids: [], precedent_ids: [], reviewer_id: null, revision: 1, reviewer_confirmed: false,
  },
}

const simulation = {
  assessments: [
    { requirement_id: 'scope-section', status: 'satisfied' as const, evidence: '审计范围' },
    { requirement_id: 'owner-list', status: 'unsatisfied' as const, evidence: '' },
  ],
  concerns: [{ id: 'contract:owner-list', category: 'contract_requirement', summary: '未满足写作要求：owner-list', requirement_id: 'owner-list', assigned_to: 'author', evidence: '' }],
  author_tasks: ['contract:owner-list'],
}

describe('WritingContractForm', () => {
  beforeEach(() => {
    contractMock.mockReset()
    createContractMock.mockReset()
    reviseContractMock.mockReset()
    confirmContractMock.mockReset()
    simulateContractMock.mockReset()
  })

  it('renders Chinese labels and an empty requirements editor', async () => {
    contractMock.mockRejectedValue({ code: 'not_found' })
    render(<WritingContractForm token="t" documentId="d1" documentType="报告" canConfirm={false} source="" />)
    expect(await screen.findByText('写作要求（逐条核对）')).toBeTruthy()
    expect(screen.getByLabelText('领域')).toBeTruthy()
    expect(screen.getByLabelText('目标读者')).toBeTruthy()
    expect(screen.getByText(/尚未添加要求/)).toBeTruthy()
    expect(screen.getByRole('button', { name: '添加要求' })).toBeTruthy()
  })

  it('adds, edits, and removes requirements', async () => {
    contractMock.mockRejectedValue({ code: 'not_found' })
    const user = userEvent.setup()
    render(<WritingContractForm token="t" documentId="d1" documentType="报告" canConfirm={false} source="" />)
    await user.click(screen.getByRole('button', { name: '添加要求' }))
    await user.click(screen.getByRole('button', { name: '添加要求' }))
    const inputs = screen.getAllByLabelText(/要求 \d 内容/)
    expect(inputs).toHaveLength(2)
    await user.type(inputs[0], '审计范围')
    await user.click(screen.getByRole('button', { name: '删除要求 2' }))
    expect(screen.getAllByLabelText(/要求 \d 内容/)).toHaveLength(1)
  })

  it('saves the contract and runs supervisor simulation against the selected version', async () => {
    contractMock.mockRejectedValue({ code: 'not_found' })
    createContractMock.mockResolvedValue(savedContract)
    simulateContractMock.mockResolvedValue(simulation)
    const user = userEvent.setup()
    render(<WritingContractForm token="t" documentId="d1" documentType="报告" canConfirm={false} source="正文包含审计范围内容" />)
    await user.click(screen.getByRole('button', { name: '添加要求' }))
    await user.type(screen.getByLabelText('要求 1 内容'), '审计范围')
    await user.click(screen.getByRole('button', { name: '创建契约' }))
    expect(await screen.findByText('契约已保存（修订版 1）。')).toBeTruthy()
    const simulateButton = screen.getByRole('button', { name: '运行模拟主管评审' })
    await user.click(simulateButton)
    expect(await screen.findByText('已满足')).toBeTruthy()
    expect(screen.getByText('未满足')).toBeTruthy()
    expect(screen.getByText('未满足写作要求：owner-list')).toBeTruthy()
    await waitFor(() => expect(simulateContractMock).toHaveBeenCalledWith('t', 'contract-1', '正文包含审计范围内容'))
  })

  it('disables simulation before the contract is saved or a version is selected', async () => {
    contractMock.mockRejectedValue({ code: 'not_found' })
    render(<WritingContractForm token="t" documentId="d1" documentType="报告" canConfirm={false} source="" />)
    const simulate = await screen.findByRole('button', { name: '请先保存契约' })
    expect((simulate as HTMLButtonElement).disabled).toBe(true)
  })
})
