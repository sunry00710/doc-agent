import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { DocumentHub } from './DocumentHub'
import { api } from '../../api/client'
import type { ChatResponse } from '../../api/client'

vi.mock('../../api/client', async (original) => {
  const actual = await original<typeof import('../../api/client')>()
  return {
    ...actual,
    api: {
      ...actual.api,
      projectMembers: vi.fn().mockResolvedValue([{ user_id: 'me', project_id: 'project-1', membership_role: 'owner' }]),
      versions: vi.fn().mockResolvedValue([]),
      reviews: vi.fn().mockResolvedValue([]),
    },
  }
})

// 用假的 compact 面板替身：直接暴露 onApplySuggestion，聚焦「草稿回填 + 提示」行为
let applySuggestion: ((text: string, kind: 'suggestion' | 'draft') => void) | undefined
vi.mock('../agent/AgentWorkspace', () => ({
  AgentWorkspace: (props: { onApplySuggestion?: (text: string, kind: 'suggestion' | 'draft') => void }) => {
    applySuggestion = props.onApplySuggestion
    return <div data-testid="agent-panel" />
  },
}))

const document = { id: 'doc-1', project_id: 'project-1', owner_id: 'me', title: '审计报告', domain: 'audit', document_type: 'report', status: 'draft' }
const version = { id: 'v1', document_id: 'doc-1', number: 1, content_sha256: 'hash', storage_key: 'key', created_by: 'me', created_at: '2026-09-01T00:00:00Z' }

function renderHub() {
  return render(
    <DocumentHub
      token="token"
      document={document}
      versions={[version]}
      source="原始正文"
      sourceReady
      selectedVersion={version}
      onSelectVersion={() => undefined}
      onVersionUploaded={() => undefined}
      currentUserId="me"
      onAgentSend={async () => ({ text: 'ok', traces: [], stop_reason: 'completed' }) as ChatResponse}
      onAgentCitations={() => undefined}
    />,
  )
}

describe('DocumentHub draft application', () => {
  beforeEach(() => sessionStorage.clear())

  it('fills the editor and shows the confirmation notice when a drafted reply is applied', async () => {
    const user = userEvent.setup()
    renderHub()
    const editor = screen.getByRole('textbox', { name: '正文草稿' })
    expect((editor as HTMLTextAreaElement).value).toBe('原始正文')

    // 项目权限（canEdit）异步加载完成后面板才挂载
    await waitFor(() => expect(applySuggestion).toBeDefined())
    applySuggestion!('# 草稿标题\n\n正文。', 'draft')

    expect((await screen.findByRole('status')).textContent).toContain('已将 Agent 草稿填入编辑器')
    expect((screen.getByRole('textbox', { name: '正文草稿' }) as HTMLTextAreaElement).value).toBe('# 草稿标题\n\n正文。')
    await user.click(screen.getByRole('button', { name: '保存为新版本' }))
    // 未配置上传 mock 时保存必然失败，但不应残留错误的成功提示
    expect(screen.queryByText(/已保存为/)).toBeNull()
  })

  it('appends plain suggestions to the draft without replacing it', async () => {
    renderHub()
    await waitFor(() => expect(applySuggestion).toBeDefined())
    applySuggestion!('增加责任主体描述', 'suggestion')

    await waitFor(() => {
      const value = (screen.getByRole('textbox', { name: '正文草稿' }) as HTMLTextAreaElement).value
      expect(value).toContain('【Agent 建议】')
      expect(value).toContain('增加责任主体描述')
    })
    const value = (screen.getByRole('textbox', { name: '正文草稿' }) as HTMLTextAreaElement).value
    expect(value).toContain('原始正文')
  })
})
