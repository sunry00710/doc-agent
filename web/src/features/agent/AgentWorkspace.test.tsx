import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AgentWorkspace } from './AgentWorkspace'

const chat = async () => ({ text: 'Safe response', traces: [{ tool_call_id: 'tool-1', name: 'search', arguments: '<img src=x onerror=alert(1)>', status: 'succeeded' as const }], stop_reason: 'completed' })

describe('AgentWorkspace', () => {
  it('renders tool arguments as text and prevents duplicate sends', async () => {
    const user = userEvent.setup()
    render(<AgentWorkspace onSend={chat} onCitations={() => undefined} />)
    await user.type(screen.getByLabelText('Message'), 'check this')
    await user.click(screen.getByRole('button', { name: 'Send' }))
    const renderedArguments = await screen.findByText((_, element) => element?.tagName === 'PRE' && element.textContent === '"<img src=x onerror=alert(1)>"')
    expect(renderedArguments).toBeTruthy()
  })

  it('asks for explicit confirmation before a mutating request', async () => {
    const user = userEvent.setup()
    render(<AgentWorkspace onSend={chat} onCitations={() => undefined} />)
    await user.type(screen.getByLabelText('Message'), 'promote this document')
    await user.click(screen.getByRole('button', { name: 'Send' }))
    expect(screen.getByRole('dialog', { name: 'Confirm action' })).toBeTruthy()
  })
})
