import type { AdminUser, AnalysisResult, AuditLog, ConfigStatus, DashboardData, Dataset, DatasetQuality, KnowledgeItem, SessionDetail, SessionSummary } from './types'

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
  createAdmin: (payload: { username: string; password: string; role?: string; dataset_ids?: number[] }) =>
    request<AdminUser>('/auth/admins', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),
  updateAdmin: (id: number, payload: { role: string; dataset_ids: number[] }) =>
    request<AdminUser>(`/auth/admins/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),
  deleteAdmin: (id: number) => request<void>(`/auth/admins/${id}`, { method: 'DELETE' }),
  dashboard: () => request<DashboardData>('/dashboard'),
  config: () => request<ConfigStatus>('/config/status'),
  datasets: () => request<Dataset[]>('/datasets'),
  dataset: (id: number) => request<Dataset>(`/datasets/${id}`),
  updateDataset: (id: number, payload: { name: string; description: string }) =>
    request<Dataset>(`/datasets/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),
  updateDatasetColumn: (id: number, column: string, description: string) =>
    request<Dataset>(`/datasets/${id}/columns/${encodeURIComponent(column)}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ description }),
    }),
  deleteDataset: (id: number) => request<void>(`/datasets/${id}`, { method: 'DELETE' }),
  datasetQuality: (id: number) => request<DatasetQuality>(`/datasets/${id}/quality`),
  importMysql: (payload: {
    host: string
    port: number
    username: string
    password: string
    database: string
    table: string
    name?: string
    description?: string
    limit?: number
  }) =>
    request<Dataset>('/datasets/mysql/import', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),
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
  updateKnowledge: (id: number, payload: { title: string; content: string; category: string; dataset_id?: number }) =>
    request<KnowledgeItem>(`/knowledge/${id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),
  uploadKnowledge: (file: File, title: string, category: string, datasetId?: number) => {
    const form = new FormData()
    form.append('file', file)
    if (title) form.append('title', title)
    form.append('category', category)
    if (datasetId) form.append('dataset_id', String(datasetId))
    return request<KnowledgeItem[]>('/knowledge/upload', { method: 'POST', body: form })
  },
  deleteKnowledge: (id: number) => request<void>(`/knowledge/${id}`, { method: 'DELETE' }),
  reindexKnowledge: () => request<Record<string, unknown>>('/knowledge/reindex', { method: 'POST' }),
  auditLogs: (query = '') => request<AuditLog[]>(`/audit/logs${query}`),
  auditExportUrl: (query = '') => `${API_BASE}/audit/logs/export.xlsx${query}`,
  reportUrl: (sessionId: string, format: 'html' | 'docx' | 'pdf' | 'md' = 'html') => `${API_BASE}/reports/${sessionId}.${format}`,
}
