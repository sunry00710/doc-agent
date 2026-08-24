import { useState } from 'react'
import { displayLabel, zhCN } from '../../app/strings'
import type { Job } from '../../api/client'

export function JobStatus({ jobs, onRetry }: { jobs: Job[]; onRetry: (jobId: string) => Promise<void> }) {
  const [retrying, setRetrying] = useState<string | null>(null)
  async function retry(jobId: string) { setRetrying(jobId); try { await onRetry(jobId) } finally { setRetrying(null) } }
  const failed = jobs.filter((job) => job.status === 'failed')
  if (!failed.length) return null
  return <section className="job-status" aria-label="可恢复的任务失败"><h2>需要处理</h2>{failed.map((job) => <article key={job.id}><p><strong>{job.job_type}</strong> 已失败，尝试次数：{job.attempts}。</p><p className="muted">{job.error?.message ?? '可以重试此任务。'}</p><button type="button" onClick={() => retry(job.id)} disabled={retrying === job.id}>{retrying === job.id ? '重试中…' : '重试任务'}</button></article>)}</section>
}
