import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type {
  Document,
  DocumentVersion,
  ReviewDetail,
} from '../api/client'
import { App } from './App'

const api = vi.hoisted(() => ({
  me: vi.fn(),
  jobs: vi.fn(),
  projects: vi.fn(),
  projectMembers: vi.fn(),
  documents: vi.fn(),
  document: vi.fn(),
  versions: vi.fn(),
  versionContent: vi.fn(),
  reviews: vi.fn(),
  review: vi.fn(),
  login: vi.fn(),
  createReview: vi.fn(),
  spaces: vi.fn(),
}))

vi.mock('../api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/client')>()),
  api,
}))

vi.mock('../features/agent/AgentWorkspace', () => ({
  AgentWorkspace: (props: { knowledgeSources?: { id: string; label: string }[]; selectedSourceIds?: string[]; onToggleSource?: (id: string) => void; targetDocuments?: { id: string; title: string }[]; activeDocumentId?: string | null; onSelectTarget?: (id: string) => void }) => (
    <div>
      <div>Agent workspace</div>
      {props.knowledgeSources?.map((source) => (
        <button key={source.id} type="button" onClick={() => props.onToggleSource?.(source.id)}>
          {`source ${source.label}${props.selectedSourceIds?.includes(source.id) ? ' selected' : ''}`}
        </button>
      ))}
      {props.targetDocuments?.map((item) => (
        <button key={item.id} type="button" onClick={() => props.onSelectTarget?.(item.id)}>
          {`target ${item.title}${props.activeDocumentId === item.id ? ' active' : ''}`}
        </button>
      ))}
    </div>
  ),
}))
vi.mock('../features/auth/LoginView', () => ({
  LoginView: () => <div>Login</div>,
}))
vi.mock('../features/citations/CitationPanel', () => ({
  CitationPanel: () => null,
}))
vi.mock('../features/documents/NewDocumentForm', () => ({
  NewDocumentForm: () => null,
}))
vi.mock('../features/knowledge/KnowledgeManager', () => ({
  KnowledgeManager: ({ onOpenHit }: { onOpenHit: (hit: { document_id: string; version_id: string }) => void }) => (
    <button
      type="button"
      onClick={() => onOpenHit({ document_id: 'doc', version_id: 'version-1' })}
    >
      open knowledge hit
    </button>
  ),
}))
vi.mock('../features/jobs/JobStatus', () => ({
  JobStatus: () => null,
}))
vi.mock('../features/reviews/ReviewPanel', () => ({
  ReviewPanel: ({ review, source }: { review: ReviewDetail; source: string }) => <section>{review.id}<p>{source}</p></section>,
}))
vi.mock('../features/reviews/ReviewQueue', () => ({
  ReviewQueue: ({ documents, onSelect }: {
    documents: Document[]
    onSelect: (
      document: Document,
      review: { id: string; version_id: string },
    ) => void
  }) => <div>{documents.flatMap((document) => (
    ['a', 'b'].map((suffix) => (
      <button
        key={`${document.id}-${suffix}`}
        onClick={() => onSelect(document, {
          id: `review-${suffix}`,
          version_id: `version-${document.id}`,
        })}
      >
        {`review ${suffix.toUpperCase()} ${document.title}`}
      </button>
    ))
  ))}</div>,
}))
vi.mock('../features/documents/DocumentHub', () => ({
  DocumentHub: ({
    document,
    versions,
    source,
    review,
    onSelectVersion,
  }: {
    document: Document | null
    versions: DocumentVersion[]
    source: string
    review: ReviewDetail | null
    onSelectVersion: (version: DocumentVersion) => void
  }) => <main>
    <div>{document?.title ?? 'no document'}</div>
    {versions.map((version) => (
      <button
        key={version.id}
        onClick={() => onSelectVersion(version)}
      >
        {version.id}
      </button>
    ))}
    <div>{source}</div>
    <div>{review?.id}</div>
  </main>,
}))

type Deferred<T> = {
  promise: Promise<T>
  resolve: (value: T) => void
}

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((next) => { resolve = next })
  return { promise, resolve }
}

function document(id: string, projectId: string): Document {
  return {
    id,
    project_id: projectId,
    owner_id: 'user-1',
    title: `Document ${id}`,
    domain: 'finance',
    document_type: 'report',
    status: 'draft',
  }
}

function version(id: string, documentId: string, number: number): DocumentVersion {
  return {
    id,
    document_id: documentId,
    number,
    content_sha256: id,
    storage_key: id,
    created_by: 'user-1',
    created_at: '2026-09-01T00:00:00Z',
  }
}

function review(id: string, documentId: string, versionId: string): ReviewDetail {
  return {
    id,
    document_id: documentId,
    version_id: versionId,
    state: 'in_review',
    reviewer_id: null,
    workflow_revision: 1,
    comments: [],
    responses: [],
  }
}

function setup(projects = [
  { id: 'project-a', name: 'Project A' },
  { id: 'project-b', name: 'Project B' },
]) {
  sessionStorage.setItem('doc-agent-token', 'token')
  sessionStorage.setItem('doc-agent-project-id', projects[0].id)
  api.me.mockResolvedValue({
    id: 'user-1',
    username: 'user',
    role: 'user',
    is_active: true,
  })
  api.jobs.mockResolvedValue({ items: [] })
  api.projects.mockResolvedValue(projects)
  api.projectMembers.mockResolvedValue([{ user_id: 'user-1', membership_role: 'reviewer' }])
  api.reviews.mockResolvedValue([])
  api.review.mockResolvedValue(null)
  api.spaces.mockResolvedValue({ items: [] })
}

describe('App request ordering', () => {
  beforeEach(() => {
    sessionStorage.clear()
    window.location.hash = 'documents'
    vi.clearAllMocks()
  })

  it('keeps documents from the latest project response', async () => {
    const projectA = deferred<Document[]>()
    const projectB = deferred<Document[]>()
    setup()
    api.documents.mockImplementation((_: string, projectId: string) => (
      projectId === 'project-a' ? projectA.promise : projectB.promise
    ))

    render(<App />)
    const user = userEvent.setup()
    await screen.findByText('user')
    await user.selectOptions(
      screen.getByLabelText('项目'),
      'project-b',
    )
    await act(async () => {
      projectB.resolve([document('b', 'project-b')])
    })
    expect(await screen.findByText('Document b')).not.toBeNull()

    await act(async () => {
      projectA.resolve([document('a', 'project-a')])
    })
    await waitFor(() => {
      expect(screen.queryByText('Document a')).toBeNull()
    })
  })

  it('keeps the latest version content when responses finish out of order', async () => {
    const contentOne = deferred<string>()
    const contentTwo = deferred<string>()
    setup([{ id: 'project-a', name: 'Project A' }])
    api.documents.mockResolvedValue([document('doc', 'project-a')])
    api.versions.mockResolvedValue([
      version('version-1', 'doc', 1),
      version('version-2', 'doc', 2),
    ])
    api.versionContent.mockImplementation((_: string, _documentId: string, number: number) => (
      number === 1 ? contentOne.promise : contentTwo.promise
    ))

    render(<App />)
    const user = userEvent.setup()
    await user.click(await screen.findByText('Document doc'))
    await user.click(await screen.findByRole('button', { name: 'version-1' }))
    await user.click(screen.getByRole('button', { name: 'version-2' }))

    await act(async () => {
      contentTwo.resolve('latest content')
    })
    expect(await screen.findByText('latest content')).not.toBeNull()
    await act(async () => {
      contentOne.resolve('stale content')
    })
    await waitFor(() => {
      expect(screen.queryByText('stale content')).toBeNull()
    })
  })

  it('keeps the latest review detail and reloads versions once per selection', async () => {
    const reviewA = deferred<ReviewDetail>()
    const reviewB = deferred<ReviewDetail>()
    const doc = document('doc', 'project-a')
    setup([{ id: 'project-a', name: 'Project A' }])
    api.documents.mockResolvedValue([doc])
    api.versions.mockResolvedValue([
      version('version-doc', 'doc', 1),
    ])
    api.versionContent.mockResolvedValue('source')
    api.reviews.mockResolvedValue([
      {
        id: 'review-a', document_id: 'doc', version_id: 'version-doc',
        state: 'in_review', reviewer_id: null, workflow_revision: 1,
      },
      {
        id: 'review-b', document_id: 'doc', version_id: 'version-doc',
        state: 'in_review', reviewer_id: null, workflow_revision: 1,
      },
    ])
    api.review.mockImplementation((_: string, id: string) => (
      id === 'review-a' ? reviewA.promise : reviewB.promise
    ))

    render(<App />)
    const user = userEvent.setup()
    await screen.findByText('user')
    await user.click(screen.getByRole('button', { name: '待我评审' }))
    await user.click(await screen.findByRole('button', { name: 'review A Document doc' }))

    await user.click(screen.getByRole('button', { name: 'review B Document doc' }))
    await act(async () => {
      reviewB.resolve(review('review-b', 'doc', 'version-doc'))
    })
    expect(await screen.findByText('review-b')).not.toBeNull()
    await act(async () => {
      reviewA.resolve(review('review-a', 'doc', 'version-doc'))
    })
    await waitFor(() => expect(screen.queryByText('review-a')).toBeNull())
    expect(api.versions).toHaveBeenCalledTimes(2)
  })

  it('restores a saved version with one versions and content request', async () => {
    setup([{ id: 'project-a', name: 'Project A' }])
    sessionStorage.setItem('doc-agent-document-id', 'doc')
    sessionStorage.setItem('doc-agent-version-id', 'version-1')
    api.documents.mockResolvedValue([document('doc', 'project-a')])
    api.versions.mockResolvedValue([version('version-1', 'doc', 1)])
    api.versionContent.mockResolvedValue('restored content')

    render(<App />)

    expect(sessionStorage.getItem('doc-agent-document-id')).toBe('doc')
    expect(sessionStorage.getItem('doc-agent-version-id')).toBe('version-1')
    expect(await screen.findByText('restored content')).not.toBeNull()
    expect(api.versions).toHaveBeenCalledOnce()
    expect(api.versionContent).toHaveBeenCalledOnce()
  })

  it('offers a return to knowledge after opening a hit', async () => {
    setup([{ id: 'project-a', name: 'Project A' }])
    api.documents.mockResolvedValue([document('doc', 'project-a')])
    api.versions.mockResolvedValue([version('version-1', 'doc', 1)])
    api.versionContent.mockResolvedValue('hit content')

    render(<App />)
    const user = userEvent.setup()
    await screen.findByText('user')
    await user.click(screen.getByRole('button', { name: '知识库' }))
    await user.click(screen.getByRole('button', { name: 'open knowledge hit' }))

    expect(await screen.findByText('hit content')).not.toBeNull()
    const back = await screen.findByRole('button', { name: '返回知识库' })
    await user.click(back)
    expect(window.location.hash).toBe('#knowledge')
  })

  it('toggles knowledge sources and persists selection', async () => {
    setup([{ id: 'project-a', name: 'Project A' }])
    api.documents.mockResolvedValue([])
    api.spaces.mockResolvedValue({ items: [{ id: 'space-1', kind: 'shared', owner_id: null, project_id: null }] })

    render(<App />)
    const user = userEvent.setup()
    await screen.findByText('user')
    await user.click(screen.getByRole('button', { name: '工作台' }))

    const source = await screen.findByRole('button', { name: 'source 共享知识库' })
    await user.click(source)
    expect(await screen.findByRole('button', { name: 'source 共享知识库 selected' })).not.toBeNull()
    expect(JSON.parse(sessionStorage.getItem('doc-agent-source-ids') ?? '[]')).toEqual(['space-1'])
  })

  it('selects a target document from the workspace without visiting the documents page', async () => {
    setup([{ id: 'project-a', name: 'Project A' }])
    api.documents.mockResolvedValue([document('doc', 'project-a')])
    api.versions.mockResolvedValue([version('version-1', 'doc', 1)])
    api.versionContent.mockResolvedValue('target content')

    render(<App />)
    const user = userEvent.setup()
    await screen.findByText('user')
    await user.click(screen.getByRole('button', { name: '工作台' }))
    await user.click(await screen.findByRole('button', { name: 'target Document doc' }))

    // 工作台就地选定目标文档：按钮进入选中态，且版本内容被加载
    expect(await screen.findByRole('button', { name: 'target Document doc active' })).not.toBeNull()
    await waitFor(() => expect(api.versionContent).toHaveBeenCalled())
  })
})
