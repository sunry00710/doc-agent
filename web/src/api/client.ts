export type ApiError = {
  code: string
  message: string
  request_id: string
  retryable: boolean
}

export type User = {
  id: string
  username: string
  role: 'user' | 'reviewer' | 'administrator'
  is_active: boolean
}

export type ToolTrace = {
  tool_call_id: string
  name: string
  arguments: unknown
  status: 'pending' | 'succeeded' | 'denied' | 'failed'
  result?: unknown
  error_code?: string
}

export type Citation = {
  chunk_id: string
  document_id: string
  version_id: string
  title: string
  heading_path: string[]
  quote: string
  start_offset: number
  end_offset: number
}

export type ChatResponse = {
  text: string
  traces: ToolTrace[]
  stop_reason: string
  request_id?: string
  citations?: Citation[]
}

export type Job = {
  id: string
  job_type: string
  status: string
  error: Record<string, string> | null
  attempts: number
  updated_at: string
}

type RequestOptions = Omit<RequestInit, 'body'> & { body?: unknown }

export class ApiClient {
  constructor(private readonly baseUrl = '/api') {}

  async login(username: string, password: string): Promise<string> {
    const body = new URLSearchParams({ username, password })
    const response = await this.request<{ access_token: string }>('/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body,
    })
    return response.access_token
  }

  me(token: string): Promise<User> {
    return this.request('/auth/me', { token })
  }

  chat(token: string, request: { text: string; confirmed?: boolean; idempotency_key?: string }): Promise<ChatResponse> {
    return this.request('/chat', { method: 'POST', token, body: request })
  }

  jobs(token: string): Promise<{ items: Job[] }> {
    return this.request('/jobs', { token })
  }

  retryJob(token: string, jobId: string): Promise<Job> {
    return this.request(`/jobs/${jobId}/retry`, { method: 'POST', token })
  }

  private async request<T>(path: string, options: RequestOptions & { token?: string } = {}): Promise<T> {
    const { body, token, headers, ...init } = options
    const response = await fetch(`${this.baseUrl}${path}`, {
      ...init,
      headers: {
        ...(body instanceof URLSearchParams ? {} : body === undefined ? {} : { 'Content-Type': 'application/json' }),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...headers,
      },
      body: body instanceof URLSearchParams ? body : body === undefined ? undefined : JSON.stringify(body),
    })
    const payload: unknown = await response.json().catch(() => null)
    if (!response.ok) {
      const error = (payload as { error?: ApiError } | null)?.error
      throw error ?? { code: 'network_error', message: 'Unable to complete the request.', request_id: '', retryable: true }
    }
    return payload as T
  }
}

export const api = new ApiClient()
