import type { DocumentVersion } from '../../api/client'

export function VersionList({ versions, selectedId, onSelect }: { versions: DocumentVersion[]; selectedId: string | null; onSelect: (version: DocumentVersion) => void }) {
  return <section className="version-list" aria-label="不可变文档版本"><h2>版本</h2>{versions.length === 0 ? <p className="muted">尚未上传版本。</p> : <ul>{versions.map((version) => <li key={version.id}><button type="button" className={version.id === selectedId ? 'selected' : ''} onClick={() => onSelect(version)}><strong>v{version.number}</strong><span>{new Date(version.created_at).toLocaleString('zh-CN')}</span></button></li>)}</ul>}</section>
}
