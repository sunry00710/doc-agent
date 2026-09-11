import { useEffect, useState } from 'react'
import { api } from '../../api/client'
import type { ProjectMember } from '../../api/client'

export function useProjectAccess(token: string, projectId: string | undefined, userId: string) {
  const key = `${token}:${projectId}:${userId}`
  const [result, setResult] = useState<{ key: string; role?: ProjectMember['membership_role']; error?: string } | null>(null)

  useEffect(() => {
    if (!projectId) return
    let active = true
    void api.projectMembers(token, projectId).then((members) => {
      if (active) setResult({ key, role: members.find((member) => member.user_id === userId)?.membership_role })
    }).catch(() => {
      if (active) setResult({ key, error: '项目权限加载失败，请刷新后重试。' })
    })
    return () => { active = false }
  }, [key, token, projectId, userId])

  const current = result?.key === key ? result : null
  return {
    loading: Boolean(projectId) && !current,
    error: current?.error,
    canEdit: Boolean(current?.role),
    canSubmit: Boolean(current?.role),
    canReview: current?.role === 'owner' || current?.role === 'reviewer',
  }
}
