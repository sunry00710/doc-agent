import { useState } from 'react'
import type { Job } from '../../api/client'

export function JobStatus({ jobs, onRetry }: { jobs: Job[]; onRetry: (jobId: string) => Promise<void> }) {
  const [retrying, setRetrying] = useState<string | null>(null)

  async function retry(jobId: string) {
    setRetrying(jobId)
    try { await onRetry(jobId) } finally { setRetrying(null) }
  }

  const failed = jobs.filter((job) => job.status === 'failed')
  if (!failed.length) return null
  return <section className="job-status" aria-label="Recoverable job failures">
    <h2>Action needed</h2>
    {failed.map((job) => <article key={job.id}>
      <p><strong>{job.job_type}</strong> failed after {job.attempts} attempt{job.attempts === 1 ? '' : 's'}.</p>
      <p className="muted">{job.error?.message ?? 'The job can be retried.'}</p>
      <button type="button" onClick={() => retry(job.id)} disabled={retrying === job.id}>{retrying === job.id ? 'Retrying…' : 'Retry job'}</button>
    </article>)}
  </section>
}
