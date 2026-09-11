import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { Document, DocumentVersion, ReviewDetail } from '../api/client'
import { App } from './App'

const api = vi.hoisted(() => ({
  me: vi.fn(), jobs: vi.fn(), projects: vi.fn(), projectMembers: vi.fn(),
  documents: vi.fn(), versions: vi.fn(), versionContent: vi.fn(),
  reviews: vi.fn(), review: vi.fn(), assignReviewer: vi.fn(), transitionReview: vi.fn(),
  spaces: vi.fn(),
  adminUsers: vi.fn(), adminUpdateUser: vi.fn(),
}))
vi.mock('../api/client', async (original) => ({
  ...(await original<typeof import('../api/client')>()), api,
}))
vi.mock('../features/agent/AgentWorkspace', () => ({ AgentWorkspace: () => null }))
vi.mock('../features/citations/CitationPanel', () => ({ CitationPanel: () => null }))
vi.mock('../features/jobs/JobStatus', () => ({ JobStatus: () => null }))

const doc: Document = { id: 'doc', project_id: 'project', owner_id: 'author', title: '采购整改方案', domain: 'audit', document_type: 'report', status: 'draft' }
const versions: DocumentVersion[] = [1, 2].map((number) => ({
  id: `v${number}`, document_id: doc.id, number, content_sha256: `hash${number}`,
  storage_key: `source${number}`, created_by: 'author', created_at: '2026-09-01T00:00:00Z',
}))
const task: ReviewDetail = { id: 'task', document_id: doc.id, version_id: 'v1', state: 'in_review', reviewer_id: 'me', workflow_revision: 1, comments: [], responses: [] }

async function openDocument() {
  render(<App />)
  const user = userEvent.setup()
  await user.click(await screen.findByRole('button', { name: doc.title }))
  await screen.findByDisplayValue('version 2 source')
  return user
}

function nav(name: string) {
  return within(screen.getByRole('navigation', { name: '主导航' })).getByRole('button', { name })
}

describe('document and review workspace boundaries', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    sessionStorage.clear()
    sessionStorage.setItem('doc-agent-token', 'token')
    window.location.hash = 'documents'
    api.me.mockResolvedValue({ id: 'me', username: 'User', role: 'reviewer', is_active: true })
    api.jobs.mockResolvedValue({ items: [] })
    api.projects.mockResolvedValue([{ id: 'project', name: 'Project' }])
    api.projectMembers.mockResolvedValue([{ user_id: 'me', membership_role: 'reviewer' }])
    api.documents.mockResolvedValue([doc])
    api.versions.mockResolvedValue(versions)
    api.versionContent.mockImplementation((_: string, _id: string, number: number) => Promise.resolve(`version ${number} source`))
    api.reviews.mockResolvedValue([task])
    api.review.mockResolvedValue(task)
    api.spaces.mockResolvedValue({ items: [] })
    api.adminUsers.mockResolvedValue([])
  })

  it('preserves the selected document version and unsaved draft while reviewing another version', async () => {
    const user = await openDocument()
    const editor = screen.getByRole('textbox', { name: '正文草稿' })
    await user.clear(editor)
    await user.type(editor, 'unsaved revision')
    expect(screen.queryByRole('tab', { name: '评审' })).toBeNull()
    expect(screen.queryByRole('button', { name: '批准' })).toBeNull()

    await user.click(nav('待我评审'))
    await user.click(await screen.findByRole('button', { name: /采购整改方案.*v1/ }))
    expect(await screen.findByText('version 1 source')).not.toBeNull()
    expect(screen.queryByRole('textbox', { name: '正文草稿' })).toBeNull()
    expect(screen.queryByRole('tablist', { name: '文档视图' })).toBeNull()
    expect(sessionStorage.getItem('doc-agent-version-id')).toBe('v2')

    await user.click(nav('文档'))
    expect(await screen.findByDisplayValue('unsaved revision')).not.toBeNull()
    expect(screen.getByText('编辑草稿 · 基于 v2')).not.toBeNull()
    await user.click(nav('工作台'))
    await user.click(nav('文档'))
    expect(await screen.findByDisplayValue('unsaved revision')).not.toBeNull()
  })

  it('opens the task-bound version explicitly without discarding the draft of another version', async () => {
    const user = await openDocument()
    await user.type(screen.getByRole('textbox', { name: '正文草稿' }), ' draft')
    await user.click(nav('待我评审'))
    await user.click(await screen.findByRole('button', { name: /采购整改方案.*v1/ }))
    await user.click(await screen.findByRole('button', { name: '打开文档工作区' }))
    expect(await screen.findByDisplayValue('version 1 source')).not.toBeNull()
    expect(sessionStorage.getItem('doc-agent-version-id')).toBe('v1')
    await user.click(screen.getByRole('button', { name: /^v2/ }))
    expect(await screen.findByDisplayValue('version 2 source draft')).not.toBeNull()
  })

  it('does not grant a global administrator project review permissions', async () => {
    api.me.mockResolvedValue({ id: 'me', username: 'Admin', role: 'admin', is_active: true })
    api.projectMembers.mockResolvedValue([{ user_id: 'me', membership_role: 'contributor' }])
    const user = await openDocument()
    await user.click(nav('管理'))
    await user.click(nav('待我评审'))
    expect(await screen.findByText('当前项目未授予你评审权限。')).not.toBeNull()
    expect(screen.queryByRole('complementary', { name: '评审队列' })).toBeNull()
    expect(screen.queryByRole('button', { name: '批准' })).toBeNull()
  })

  it('allows a project reviewer with a normal global role to process their assigned task', async () => {
    api.me.mockResolvedValue({ id: 'me', username: 'User', role: 'user', is_active: true })
    const user = await openDocument()
    await user.click(nav('待我评审'))
    await user.click(await screen.findByRole('button', { name: /采购整改方案.*v1/ }))
    expect(await screen.findByRole('button', { name: '批准' })).not.toBeNull()
    api.transitionReview.mockResolvedValue({ ...task, state: 'approved' })
    await user.click(screen.getByRole('button', { name: '批准' }))
    await waitFor(() => expect(api.transitionReview).toHaveBeenCalledWith('token', 'task', 'approved', 1))
  })

  it('hides review actions when an opened task has been reassigned', async () => {
    api.review.mockResolvedValue({ ...task, reviewer_id: 'someone-else' })
    const user = await openDocument()
    await user.click(nav('待我评审'))
    await user.click(await screen.findByRole('button', { name: /采购整改方案.*v1/ }))
    await screen.findByText('version 1 source')
    expect(screen.queryByRole('button', { name: '批准' })).toBeNull()
    expect(screen.queryByRole('textbox', { name: '请求修改意见' })).toBeNull()
  })

  it('preserves review opinion drafts after a workflow revision conflict', async () => {
    api.transitionReview.mockRejectedValue({ code: 'version_conflict' })
    const user = await openDocument()
    await user.click(nav('待我评审'))
    await user.click(await screen.findByRole('button', { name: /采购整改方案.*v1/ }))
    await user.type(await screen.findByRole('textbox', { name: '请求修改意见' }), 'keep this opinion')
    await user.click(screen.getByRole('button', { name: '批准' }))
    await waitFor(() => expect(api.review).toHaveBeenCalledTimes(2))
    expect(await screen.findByDisplayValue('keep this opinion')).not.toBeNull()
    expect(await screen.findByText(/审核内容已发生变化/)).not.toBeNull()
  })

  it('shows only actionable assigned tasks and claimable submitted tasks', async () => {
    api.reviews.mockResolvedValue([
      task,
      { ...task, id: 'other', reviewer_id: 'other-user' },
      { ...task, id: 'done', state: 'approved' },
      { ...task, id: 'orphan', reviewer_id: null },
      { ...task, id: 'claimable', reviewer_id: null, state: 'submitted' },
    ])
    api.review.mockResolvedValue({ ...task, id: 'claimable', reviewer_id: null, state: 'submitted' })
    const user = await openDocument()
    await user.click(nav('待我评审'))
    await screen.findByRole('tab', { name: '待我评审 1' })
    await user.click(screen.getByRole('tab', { name: '待领取 1' }))
    await user.click(screen.getByRole('button', { name: /采购整改方案.*v1/ }))
    expect(await screen.findByRole('button', { name: '领取评审任务' })).not.toBeNull()
    expect(screen.queryByRole('button', { name: '批准' })).toBeNull()
  })
})
