import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AgentWorkspace } from './AgentWorkspace'

const chat = async () => ({ text: '安全回复', traces: [{ tool_call_id: 'tool-1', name: 'search', arguments: '<img src=x onerror=alert(1)>', status: 'succeeded' as const }], stop_reason: 'completed' })

describe('AgentWorkspace', () => {
  it('renders tool arguments as text and prevents duplicate sends', async () => {
    const user = userEvent.setup()
    render(<AgentWorkspace onSend={chat} onCitations={() => undefined} />)
    await user.type(screen.getByLabelText('消息'), '检查文档')
    await user.click(screen.getByRole('button', { name: '发送' }))
    const renderedArguments = await screen.findByText((_, element) => element?.tagName === 'PRE' && element.textContent === '"<img src=x onerror=alert(1)>"')
    expect(renderedArguments).toBeTruthy()
  })

  it('asks for explicit confirmation before a Chinese mutating request', async () => {
    const user = userEvent.setup()
    render(<AgentWorkspace onSend={chat} onCitations={() => undefined} />)
    await user.type(screen.getByLabelText('消息'), '申请晋升这份文档')
    await user.click(screen.getByRole('button', { name: '发送' }))
    expect(screen.getByRole('dialog', { name: '确认操作' })).toBeTruthy()
  })

  it('shows the bound context with document version', () => {
    render(<AgentWorkspace onSend={chat} onCitations={() => undefined} context={{ projectName: '演示项目', documentTitle: '审计报告', versionLabel: 'v1' }} />)
    const banner = screen.getByLabelText('Agent 上下文')
    expect(banner.textContent).toContain('演示项目')
    expect(banner.textContent).toContain('审计报告（v1）')
  })

  it('warns when no document version is selected', () => {
    render(<AgentWorkspace onSend={chat} onCitations={() => undefined} context={{ projectName: '演示项目', documentTitle: null, versionLabel: null }} />)
    expect(screen.getByText(/尚未选择文档版本/)).toBeTruthy()
  })

  it('prompts to select a project when context is missing', () => {
    render(<AgentWorkspace onSend={chat} onCitations={() => undefined} />)
    expect(screen.getByText(/请先在左侧选择项目/)).toBeTruthy()
  })
})
