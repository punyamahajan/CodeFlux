/** Typed API client for OmniKey /api endpoints */

export interface User {
  id: string
  org_id: string
  email: string
  role: 'admin' | 'member'
  org_name?: string
  created_at?: string
}

export interface ProviderCredential {
  id: string
  provider: string
  key_hint: string
  enabled: boolean
  last_used_at?: string | null
  created_at?: string
}

export interface PlatformKey {
  id: string
  org_id: string
  user_id: string
  name: string
  key_prefix: string
  credit_limit_micro: number
  credit_remaining_micro: number
  rpm_limit: number
  allowed_routes: string[]
  expires_at?: string | null
  revoked_at?: string | null
  created_at: string
  last_used_at?: string | null
}

export interface RouteConfig {
  alias: string
  strategy: string
  task_tag?: string | null
  pii_redaction: boolean
  total_timeout_seconds: number
  candidates: Array<{
    provider: string
    model: string
    weight?: number
    timeout_seconds?: number
  }>
}

export interface LimitRequest {
  id: string
  org_id: string
  key_id: string
  key_name?: string
  user_id: string
  user_email?: string
  requested_credit_micro: number
  current_limit_micro: number
  reason: string
  status: 'pending' | 'approved' | 'denied'
  created_at: string
}

export interface RequestTrace {
  id: string
  org_id: string
  key_id?: string | null
  provider?: string | null
  model?: string | null
  status_code?: number | null
  latency_ms?: number | null
  prompt_tokens: number
  completion_tokens: number
  cost_micro: number
  facts: Record<string, any>
  created_at: string
}

export interface ExplainResult {
  headline: string
  bullets: string[]
  facts: Record<string, any>
}

export interface NarrationResult {
  narration?: string
  bullets?: string[]
  cached?: boolean
  guard?: string | null
}

export async function apiFetch<T = any>(endpoint: string, options: RequestInit = {}): Promise<T> {
  const res = await fetch(endpoint, {
    ...options,
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
      ...options.headers,
    },
  })

  if (!res.ok) {
    let errData: any
    try {
      errData = await res.json()
    } catch {
      errData = { error: { message: `HTTP ${res.status}: ${res.statusText}` } }
    }
    const message =
      errData?.error?.message || errData?.detail || errData?.message || `Request failed (${res.status})`
    throw new Error(message)
  }

  return res.json()
}

export const api = {
  // Auth
  me: () => apiFetch<User>('/api/auth/me'),
  login: (data: { email: string; password: string }) =>
    apiFetch<{ token: string; user: User }>('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  signup: (data: { email: string; password: string; org_name?: string; invite_code?: string }) =>
    apiFetch<{ token: string; user: User }>('/api/auth/signup', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  logout: () => apiFetch('/api/auth/logout', { method: 'POST' }),

  // Vault
  getVault: () => apiFetch<ProviderCredential[]>('/api/admin/vault'),
  addCredential: (data: { provider: string; key: string }) =>
    apiFetch<ProviderCredential>('/api/admin/vault', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  toggleCredential: (id: string, enabled: boolean) =>
    apiFetch<ProviderCredential>(`/api/admin/vault/${id}`, {
      method: 'PATCH',
      body: JSON.stringify({ enabled }),
    }),
  deleteCredential: (id: string) =>
    apiFetch(`/api/admin/vault/${id}`, { method: 'DELETE' }),

  // Keys
  getKeys: () => apiFetch<PlatformKey[]>('/api/admin/keys'),
  createKey: (data: {
    name: string
    credit_limit_micro: number
    rpm_limit?: number
    allowed_routes?: string[]
    expires_at?: string | null
  }) =>
    apiFetch<{ key: PlatformKey; plaintext: string }>('/api/admin/keys', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  revokeKey: (id: string) =>
    apiFetch<PlatformKey>(`/api/admin/keys/${id}/revoke`, { method: 'POST' }),

  // Member own keys
  getMemberKeys: () => apiFetch<PlatformKey[]>('/api/member/keys'),
  createMemberKey: (data: { name: string }) =>
    apiFetch<{ key: PlatformKey; plaintext: string }>('/api/member/keys', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  // Routes
  getRoutes: () => apiFetch<RouteConfig[]>('/api/admin/routes'),
  saveRoute: (data: RouteConfig) =>
    apiFetch<RouteConfig>('/api/admin/routes', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  // Requests
  getAdminRequests: () => apiFetch<LimitRequest[]>('/api/admin/requests'),
  approveRequest: (id: string, approved_limit_micro?: number) =>
    apiFetch<LimitRequest>(`/api/admin/requests/${id}/approve`, {
      method: 'POST',
      body: JSON.stringify({ approved_limit_micro }),
    }),
  denyRequest: (id: string) =>
    apiFetch<LimitRequest>(`/api/admin/requests/${id}/deny`, { method: 'POST' }),
  createLimitRequest: (data: { key_id: string; requested_credit_micro: number; reason: string }) =>
    apiFetch<LimitRequest>('/api/member/requests', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  getMemberRequests: () => apiFetch<LimitRequest[]>('/api/member/requests'),

  // Usage & Traces
  getAdminUsage: () => apiFetch<any>('/api/admin/usage'),
  getMemberUsage: () => apiFetch<any>('/api/member/usage'),
  getTraces: () => apiFetch<RequestTrace[]>('/api/admin/traces'),

  // Explain
  explain: (kind: string, id: string) =>
    apiFetch<ExplainResult>(`/api/explain/${kind}/${id}`),
  narrate: (kind: string, id: string) =>
    apiFetch<NarrationResult>(`/api/explain/${kind}/${id}/narrate`, { method: 'POST' }),

  // Playground & Arenas
  playgroundChat: (data: {
    format?: 'openai' | 'gemini'
    model: string
    messages: Array<{ role: string; content: string }>
    key_id?: string
  }) =>
    apiFetch<any>('/api/playground/chat', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  arenaCompare: (data: {
    prompt: string
    models: string[]
    judge?: boolean
    judge_model?: string
    key_id?: string
  }) =>
    apiFetch<any>('/api/arena/compare', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  arenaDebate: (data: {
    topic: string
    model_a: string
    model_b: string
    judge_model?: string
    rounds?: number
    key_id?: string
  }) =>
    apiFetch<any>('/api/arena/debate', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
}
