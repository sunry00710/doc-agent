import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { VersionList } from './VersionList'

const versions = [
  { id: 'v1', document_id: 'doc', number: 1, content_sha256: 'a', storage_key: 'a', created_by: 'u', created_at: '2026-08-21T00:00:00Z' },
  { id: 'v2', document_id: 'doc', number: 2, content_sha256: 'b', storage_key: 'b', created_by: 'u', created_at: '2026-08-22T00:00:00Z' },
]

describe('VersionList', () => {
  it('keeps immutable version selection explicit', async () => {
    const user = userEvent.setup()
    const onSelect = vi.fn()
    render(<VersionList versions={versions} selectedId="v1" onSelect={onSelect} />)
    expect(screen.getByRole('button', { name: /v1/ }).className).toContain('selected')
    await user.click(screen.getByRole('button', { name: /v2/ }))
    expect(onSelect).toHaveBeenCalledWith(versions[1])
  })
})
