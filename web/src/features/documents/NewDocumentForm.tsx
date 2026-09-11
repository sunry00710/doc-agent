import { useState } from 'react'
import type { FormEvent } from 'react'
import { displayError } from '../../app/strings'
import { api } from '../../api/client'
import type { ApiError, Document } from '../../api/client'
import { FilePicker } from './FilePicker'

type NewDocumentFormProps = {
  token: string
  projectId: string
  onCreated: (document: Document) => void
}

export function NewDocumentForm({ token, projectId, onCreated }: NewDocumentFormProps) {
  const [title, setTitle] = useState('')
  const [domain, setDomain] = useState('')
  const [documentType, setDocumentType] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (busy) return
    if (!title.trim() || !file) {
      setError('请填写文档标题并选择要上传的文件。')
      return
    }
    setError('')
    setBusy(true)
    try {
      const document = await api.createDocument(token, {
        project_id: projectId,
        title: title.trim(),
        domain: domain.trim() || '综合',
        document_type: documentType.trim() || '报告',
      })
      await api.uploadVersion(token, document.id, file)
      setTitle('')
      setDomain('')
      setDocumentType('')
      setFile(null)
      onCreated(document)
    } catch (reason) {
      setError(displayError((reason as Partial<ApiError>).code, '文档创建失败。'))
    } finally {
      setBusy(false)
    }
  }

  return <form className="new-document" onSubmit={submit} aria-label="新建文档">
    <h2>新建文档</h2>
    <label>标题<input value={title} onChange={(event) => setTitle(event.target.value)} placeholder="文档标题" /></label>
    <div className="form-row">
      <label>领域<input value={domain} onChange={(event) => setDomain(event.target.value)} placeholder="默认：综合" /></label>
      <label>类型<input value={documentType} onChange={(event) => setDocumentType(event.target.value)} placeholder="默认：报告" /></label>
    </div>
    <div className="field-label">正文文件（v1）</div>
    <FilePicker label="正文文件" file={file} onSelect={setFile} disabled={busy} />
    {error && <p className="error" role="alert">{error}</p>}
    <button type="submit" disabled={busy}>{busy ? '创建中…' : '创建并上传 v1'}</button>
  </form>
}
