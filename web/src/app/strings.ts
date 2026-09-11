export const zhCN = {
  role: {
    user: '员工（下级）',
    reviewer: '上级审核',
    admin: '管理员',
  },
  reviewState: {
    draft: '草稿',
    submitted: '已提交',
    in_review: '审核中',
    changes_requested: '需修改',
    resubmitted: '已重新提交',
    approved: '已通过',
    promotion_pending: '等待晋升',
    indexed: '已索引',
    archived: '已归档',
  },
  status: {
    pending: '等待中',
    succeeded: '成功',
    denied: '已拒绝',
    failed: '失败',
    queued: '排队中',
    running: '处理中',
    retrying: '重试中',
    cancelled: '已取消',
    approved: '已批准',
    rejected: '已驳回',
    active: '已启用',
    revoked: '已撤销',
  },
  promotionStatus: {
    pending_review: '等待评审',
    approved: '已批准',
    rejected: '已驳回',
    indexing: '索引中',
    indexed: '已索引',
    failed: '索引失败',
    revoked: '已撤销',
  },
  qualityStatus: {
    passed: '质量门通过',
    failed: '质量门未通过',
    needs_human_review: '需人工复核',
  },
  space: {
    personal: '个人知识库',
    project: '项目知识库',
    shared: '共享知识库',
    standard: '规范知识库',
  },
  comparisonCategory: {
    addition: '新增',
    deletion: '删除',
    modification: '修改',
    semantic_rewrite: '语义改写',
    data_change: '数据变化',
    structure_change: '结构调整',
    tone_change: '语气变化',
    comment_response: '批注回应',
    unchanged: '无变化',
  },
  comparisonEngine: {
    llm: '语义对比 · 模型',
    heuristic: '本地启发式 · 未接入模型',
    difflib: '逐行差异 · 已降级',
  },
} as const

export function displayLabel(
  labels: Record<string, string>,
  value: string | null | undefined,
): string {
  return value ? labels[value] ?? value : '未设置'
}

export function displayError(code: string | undefined, fallback: string): string {
  const errors: Record<string, string> = {
    authentication_error: '用户名或密码错误。',
    unauthorized: '请先登录后再继续。',
    forbidden: '你没有执行此操作的权限。',
    permission_denied: '你没有执行此操作的权限。',
    not_found: '未找到请求的内容。',
    validation_error: '提交的数据无效，请检查后重试。',
    version_conflict: '内容已发生变化，请刷新后重试。',
    provider_unavailable: '模型服务暂时不可用，请稍后重试。',
    network_error: '请求无法完成，请检查网络后重试。',
  }
  return errors[code ?? ''] ?? fallback
}
