import { useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { displayError } from '../../app/strings'
import { api } from '../../api/client'
import type { ApiError, DocumentVersion } from '../../api/client'

type UploadVersionFormProps = {
  token: string
  documentId: string
  nextNumber: number
  onUploaded: (version: DocumentVersion) => void
}

export function UploadVersionForm({ token, documentId, nextNumber, onUploaded }: UploadVersionFormProps) {
  const [file, setFile] = useState<File | null>(null)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (busy) return
    if (!file) {
      setError('请选择要上传的文件。')
      return
    }
    setError('')
    setNotice('')
    setBusy(true)
    try {
      const version = await api.uploadVersion(token, documentId, file)
      setFile(null)
      if (fileRef.current) fileRef.current.value = ''
      setNotice(`已创建 v${version.number}。`)
      onUploaded(version)
    } catch (reason) {
      setError(displayError((reason as Partial<ApiError>).code, '版本上传失败。'))
    } finally {
      setBusy(false)
    }
  }

  return <form className="upload-version" onSubmit={submit} aria-label="上传新版本">
    <h3>上传新版本（v{nextNumber}）</h3>
    <input ref={fileRef} type="file" aria-label="新版本文件" onChange={(event) => { setFile(event.target.files?.[0] ?? null); setNotice('') }} />
    <button type="submit" disabled={!file || busy}>{busy ? '上传中…' : '上传为新版本'}</button>
    {notice && <p className="success" role="status">{notice}</p>}
    {error && <p className="error" role="alert">{error}</p>}
  </form>
}
