import type { AdminUser, AnalysisResult, ConfigStatus, DashboardData, Dataset, KnowledgeItem, SessionDetail, SessionSummary } from './types'

const API_BASE = import.meta.env.VITE_API_BASE || '/api/v1'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, { ...init, credentials: 'include' })
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: '请求失败' }))
    throw new Error(body.detail || `请求失败 (${response.status})`)
  }
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

export const api = {
  login: (username: string, password: string) =>
    request<{ admin: AdminUser }>('/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    }),
  logout: () => request<void>('/auth/logout', { method: 'POST' }),
  me: () => request<{ admin: AdminUser }>('/auth/me'),
  admins: () => request<AdminUser[]>('/auth/admins'),
  createAdmin: (payload: { username: string; password: string }) =>
    request<AdminUser>('/auth/admins', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),
  dashboard: () => request<DashboardData>('/dashboard'),
  config: () => request<ConfigStatus>('/config/status'),
  datasets: () => request<Dataset[]>('/datasets'),
  dataset: (id: number) => request<Dataset>(`/datasets/${id}`),
  knowledge: (datasetId?: number) => request<KnowledgeItem[]>(`/knowledge${datasetId ? `?dataset_id=${datasetId}` : ''}`),
  sessions: () => request<SessionSummary[]>('/sessions'),
  session: (id: string) => request<SessionDetail>(`/sessions/${id}`),
  deleteSession: (id: string) => request<void>(`/sessions/${id}`, { method: 'DELETE' }),
  analyze: (question: string, datasetId?: number, sessionId?: string) =>
    request<AnalysisResult>('/agent/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question, dataset_id: datasetId, session_id: sessionId }),
    }),
  upload: (file: File, name: string, description: string) => {
    const form = new FormData()
    form.append('file', file)
    if (name) form.append('name', name)
    form.append('description', description)
    return request<Dataset>('/datasets/upload', { method: 'POST', body: form })
  },
  createKnowledge: (payload: { title: string; content: string; category: string; dataset_id?: number }) =>
    request<KnowledgeItem>('/knowledge', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),
  deleteKnowledge: (id: number) => request<void>(`/knowledge/${id}`, { method: 'DELETE' }),
  reportUrl: (sessionId: string, format: 'html' | 'docx' | 'pdf' = 'html') => `${API_BASE}/reports/${sessionId}.${format}`,
}
