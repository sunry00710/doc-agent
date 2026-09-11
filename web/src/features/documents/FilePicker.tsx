import { useRef, useState } from 'react'

type FilePickerProps = {
  label: string
  file: File | null
  onSelect: (file: File | null) => void
  disabled?: boolean
}

/**
 * 苹果风文件选择器：隐藏浏览器原生控件（"选择文件 | 未选择文件"样式老旧），
 * 用绑定按钮触发 + 显示文件名/大小，与整体设计语言一致。
 */
export function FilePicker({ label, file, onSelect, disabled = false }: FilePickerProps) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [dragOver, setDragOver] = useState(false)

  function pick(next: File | null) {
    onSelect(next)
    // 允许连续选择同一文件（input 值不清空时 change 不触发）
    if (inputRef.current) inputRef.current.value = ''
  }

  return (
    <div
      className={dragOver ? 'file-picker drag-over' : 'file-picker'}
      onDragOver={(event) => { event.preventDefault(); if (!disabled) setDragOver(true) }}
      onDragLeave={() => setDragOver(false)}
      onDrop={(event) => {
        event.preventDefault()
        setDragOver(false)
        if (disabled) return
        const dropped = event.dataTransfer.files?.[0]
        if (dropped) pick(dropped)
      }}
    >
      <input
        ref={inputRef}
        type="file"
        className="file-picker-input"
        aria-label={label}
        disabled={disabled}
        onChange={(event) => pick(event.target.files?.[0] ?? null)}
      />
      <button
        type="button"
        className="file-picker-trigger"
        disabled={disabled}
        onClick={() => inputRef.current?.click()}
      >
        {file ? '更换' : '浏览'}
      </button>
      {file
        ? <span className="file-picker-name" title={file.name}>
            {file.name}
            <span className="muted"> · {(file.size / 1024).toFixed(1)} KB</span>
          </span>
        : <span className="file-picker-hint muted">未选择 · 可拖入</span>}
      {file && <button type="button" className="file-picker-clear" aria-label="清除已选文件" disabled={disabled} onClick={() => pick(null)}>×</button>}
    </div>
  )
}
