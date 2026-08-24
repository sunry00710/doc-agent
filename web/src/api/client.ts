export type ApiError = { code: string; message: string; request_id: string; retryable: boolean }
export type User = { id: string; username: string; role: 'user' | 'reviewer' | 'admin'; is_active: boolean }
export type ToolTrace = { tool_call_id: string; name: string; arguments: unknown; status: 'pending' | 'succeeded' | 'denied' | 'failed'; result?: unknown; error_code?: string }
export type Citation = { chunk_id: string; document_id: string; version_id: string; title: string; heading_path: string[]; quote: string; start_offset: number; end_offset: number }
export type ChatResponse = { text: string; traces: ToolTrace[]; stop_reason: string; request_id?: string; citations?: Citation[] }
export type Job = { id: string; job_type: string; status: string; error: Record<string, string> | null; attempts: number; updated_at: string }
export type Document = { id: string; project_id: string; owner_id: string; title: string; domain: string; document_type: string; status: string }
export type DocumentVersion = { id: string; document_id: string; number: number; content_sha256: string; storage_key: string; created_by: string; created_at: string }
export type Review = { id: string; document_id: string; version_id: string; state: string; reviewer_id: string | null; workflow_revision: number }
export type ReviewComment = { id: string; review_id: string; version_id: string; source_range: { start: number; end: number }; text: string; status: string; created_by: string }
export type CommentResponse = { id: string; comment_id: string; response_version_id: string; assessment: string; reviewer_confirmed: boolean }
export type ReviewDetail = Review & { comments: ReviewComment[]; responses: CommentResponse[] }
export type Requirement = { id: string; text: string; mandatory: boolean }
export type ContractRevision = { domain: string; document_type: string; subject_organization: string; reporting_period: string; purpose: string; audience: string; requirements: Requirement[]; standard_ids: string[]; precedent_ids: string[]; reviewer_id: string | null; revision: number; reviewer_confirmed: boolean }
export type Contract = { id: string; project_id: string; document_id: string; active_revision: number; revision: ContractRevision }
export type ContractAssessment = { requirement_id: string; status: 'satisfied' | 'unsatisfied' | 'unknown'; evidence: string }
export type SupervisorConcern = { id: string; category: string; summary: string; requirement_id: string | null; assigned_to: string; evidence: string }
export type SupervisorSimulation = { assessments: ContractAssessment[]; concerns: SupervisorConcern[]; author_tasks: string[] }
export type KnowledgeSpace = { id: string; kind: string; owner_id: string | null; project_id: string | null }
export type SearchHit = { chunk_id: string; document_id: string; version_id: string; title: string; heading_path: string[]; quote: string; start_offset: number; end_offset: number }
export type IngestResult = { document_id: string; space_id: string; version_id: string; state: string }
export type Promotion = { id: string; version_id: string; target_space_id: string; requested_by: string; reviewed_by: string | null; status: string; quality_status: string; findings: Record<string, unknown>[]; policy_version: string; authority_level: number; public_authority: boolean; document_title?: string | null; version_number?: number | null }
export type ComparisonChange = { category: string; summary: string; version_a_id: string; version_b_id: string; citations: string[] }
export type Comparison = { version_a_id: string; version_b_id: string; changes: ComparisonChange[]; summary: string; citations: string[] }

type RequestOptions = Omit<RequestInit, 'body'> & { body?: unknown }

export class ApiClient {
  constructor(private readonly baseUrl = '/api') {}
  async login(username: string, password: string): Promise<string> { return (await this.request<{ access_token: string }>('/auth/login', { method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded' }, body: new URLSearchParams({ username, password }) })).access_token }
  me(token: string): Promise<User> { return this.request('/auth/me', { token }) }
  chat(token: string, request: { text: string; confirmed?: boolean; idempotency_key?: string; project_id?: string; document_version_id?: string }): Promise<ChatResponse> { return this.request('/chat', { method: 'POST', token, body: request }) }
  jobs(token: string): Promise<{ items: Job[] }> { return this.request('/jobs', { token }) }
  retryJob(token: string, jobId: string): Promise<Job> { return this.request(`/jobs/${jobId}/retry`, { method: 'POST', token }) }
  projects(token: string): Promise<{ id: string; name: string }[]> { return this.request('/projects', { token }) }
  documents(token: string, projectId: string): Promise<Document[]> { return this.request(`/documents?project_id=${encodeURIComponent(projectId)}`, { token }) }
  document(token: string, documentId: string): Promise<Document> { return this.request(`/documents/${documentId}`, { token }) }
  createDocument(token: string, data: { project_id: string; title: string; domain: string; document_type: string }): Promise<Document> { return this.request('/documents', { method: 'POST', token, body: data }) }
  uploadVersion(token: string, documentId: string, file: File): Promise<DocumentVersion> { return this.request(`/documents/${documentId}/versions`, { method: 'POST', token, body: buildUploadForm(file) }) }
  versions(token: string, documentId: string): Promise<DocumentVersion[]> { return this.request(`/documents/${documentId}/versions`, { token }) }
  versionContent(token: string, documentId: string, number: number): Promise<string> { return this.requestText(`/documents/${documentId}/versions/${number}`, { token }) }
  reviews(token: string, documentId: string): Promise<Review[]> { return this.request(`/reviews/documents/${documentId}`, { token }) }
  review(token: string, reviewId: string): Promise<ReviewDetail> { return this.request(`/reviews/${reviewId}`, { token }) }
  createReview(token: string, documentId: string, versionId: string): Promise<Review> { return this.request(`/reviews/documents/${documentId}`, { method: 'POST', token, body: { version_id: versionId } }) }
  assignReviewer(token: string, reviewId: string, reviewerId: string, expected_revision: number): Promise<Review> { return this.request(`/reviews/${reviewId}/assign`, { method: 'POST', token, body: { reviewer_id: reviewerId, expected_revision } }) }
  transitionReview(token: string, reviewId: string, state: string, expected_revision: number): Promise<Review> { return this.request(`/reviews/${reviewId}/transition`, { method: 'POST', token, body: { state, expected_revision } }) }
  addComment(token: string, reviewId: string, source_range: { start: number; end: number }, text: string, expected_revision: number): Promise<ReviewComment> { return this.request(`/reviews/${reviewId}/comments`, { method: 'POST', token, body: { source_range, text, expected_revision } }) }
  contract(token: string, documentId: string): Promise<Contract> { return this.request(`/quality/documents/${documentId}/contract`, { token }) }
  createContract(token: string, documentId: string, data: Omit<ContractRevision, 'revision' | 'reviewer_confirmed'>): Promise<Contract> { return this.request(`/quality/documents/${documentId}/contract`, { method: 'POST', token, body: data }) }
  reviseContract(token: string, contractId: string, data: Omit<ContractRevision, 'revision' | 'reviewer_confirmed'>): Promise<Contract> { return this.request(`/quality/contracts/${contractId}/revisions`, { method: 'POST', token, body: data }) }
  confirmContract(token: string, contractId: string): Promise<Contract> { return this.request(`/quality/contracts/${contractId}/confirm`, { method: 'POST', token }) }
  simulateContract(token: string, contractId: string, source: string): Promise<SupervisorSimulation> { return this.request(`/quality/contracts/${contractId}/simulate?source=${encodeURIComponent(source)}`, { method: 'POST', token }) }
  compare(token: string, version_a_id: string, version_b_id: string, comparison_type: string): Promise<Comparison> { return this.request('/quality/comparisons', { method: 'POST', token, body: { version_a_id, version_b_id, comparison_type } }) }
  spaces(token: string): Promise<{ items: KnowledgeSpace[] }> { return this.request('/knowledge/spaces', { token }) }
  createPersonalSpace(token: string): Promise<KnowledgeSpace> { return this.request('/knowledge/spaces', { method: 'POST', token, body: { kind: 'personal' } }) }
  ingestToSpace(token: string, spaceId: string, versionId: string): Promise<IngestResult> { return this.request(`/knowledge/spaces/${spaceId}/ingest`, { method: 'POST', token, body: { version_id: versionId } }) }
  searchKnowledge(token: string, query: string): Promise<SearchHit[]> { return this.request('/knowledge/search', { method: 'POST', token, body: { query, limit: 10, mode: 'hybrid' } }) }
  promotions(token: string, versionId?: string): Promise<{ items: Promotion[] }> { return this.request(`/knowledge/promotions${versionId ? `?version_id=${encodeURIComponent(versionId)}` : ''}`, { token }) }
  createPromotion(token: string, body: { version_id: string; target_space_id: string; findings: Record<string, unknown>[]; public_authority: boolean; authority_level: number }): Promise<Promotion> { return this.request('/knowledge/promotions', { method: 'POST', token, body }) }
  reviewPromotion(token: string, requestId: string, approved: boolean): Promise<Promotion> { return this.request(`/knowledge/promotions/${requestId}/review`, { method: 'POST', token, body: { approved } }) }
  activatePromotion(token: string, requestId: string): Promise<Promotion> { return this.request(`/knowledge/promotions/${requestId}/activate`, { method: 'POST', token }) }
  revokePromotion(token: string, requestId: string): Promise<Promotion> { return this.request(`/knowledge/promotions/${requestId}/revoke`, { method: 'POST', token }) }

  private async requestText(path: string, options: RequestOptions & { token?: string } = {}): Promise<string> {
    const { token, headers, ...init } = options
    const response = await fetch(`${this.baseUrl}${path}`, { ...init, body: undefined, headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}), ...headers } })
    if (!response.ok) throw await this.error(response)
    return response.text()
  }
  private async request<T>(path: string, options: RequestOptions & { token?: string } = {}): Promise<T> {
    const { body, token, headers, ...init } = options
    const isForm = body instanceof FormData
    const response = await fetch(`${this.baseUrl}${path}`, { ...init, headers: { ...(isForm || body instanceof URLSearchParams || body === undefined ? {} : { 'Content-Type': 'application/json' }), ...(token ? { Authorization: `Bearer ${token}` } : {}), ...headers }, body: isForm || body instanceof URLSearchParams ? body as BodyInit : body === undefined ? undefined : JSON.stringify(body) })
    if (!response.ok) throw await this.error(response)
    return await response.json() as T
  }
  private async error(response: Response): Promise<ApiError> { const payload: unknown = await response.json().catch(() => null); return (payload as { error?: ApiError } | null)?.error ?? { code: 'network_error', message: 'Unable to complete the request.', request_id: '', retryable: true } }
}

function buildUploadForm(file: File): FormData {
  const form = new FormData()
  form.append('file', file, file.name)
  return form
}

export const api = new ApiClient()
