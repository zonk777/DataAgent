export type ViewName = 'overview' | 'analyst' | 'datasets' | 'knowledge' | 'accounts' | 'audit' | 'settings'

export interface AdminUser {
  id: number
  username: string
  role: 'initial_admin' | 'admin' | 'data_analyst' | 'business_user'
  dataset_permissions: number[]
  is_initial_admin: boolean
  created_by: number | null
  created_at: string
}

export interface Dataset {
  id: number
  name: string
  description: string
  source_type: string
  table_name: string
  row_count: number
  column_count: number
  status: string
  created_at: string
  columns?: DatasetColumn[]
  preview?: Record<string, unknown>[]
}

export interface DatasetColumn {
  name: string
  data_type: string
  description: string
  sample_value: string | null
  null_rate: number
}

export interface DatasetQuality {
  dataset_id: number
  row_count: number
  column_count: number
  duplicate_rows: number
  missing: Array<{ column: string; missing_count: number; missing_rate: number }>
  outliers: Array<{ column: string; outlier_count: number }>
  summary: string[]
}

export interface KnowledgeItem {
  id: number
  title: string
  content: string
  category: string
  dataset_id: number | null
  created_at: string
  score?: number
  retrieval_mode?: string
}

export interface AnalysisResult {
  session_id: string
  message: string
  intent: string
  plan: string[]
  sql: string
  columns: string[]
  rows: Record<string, string | number | null>[]
  chart: {
    type: 'bar' | 'line' | 'pie' | 'scatter' | 'none'
    title: string
    x_field: string | null
    y_field: string | null
    series_name: string | null
    series_field: string | null
    series_fields?: string[]
  }
  insights: string[]
  knowledge_refs: KnowledgeItem[]
  execution_mode: string
  answer_type: 'data_analysis' | 'knowledge_qa'
  context_applied: boolean
  effective_question: string
}

export interface ChatMessage {
  id?: number
  role: 'user' | 'assistant'
  content: string
  payload?: AnalysisResult | null
  created_at?: string
}

export interface SessionSummary {
  id: string
  title: string
  dataset_id: number | null
  created_at: string
  updated_at: string
  message_count: number
  last_message: string | null
}

export interface SessionDetail extends SessionSummary {
  messages: ChatMessage[]
}

export interface DashboardData {
  dataset_count: number
  knowledge_count: number
  analysis_count: number
  session_count: number
  recent_sessions: SessionSummary[]
}

export interface ConfigStatus {
  llm_configured: boolean
  llm_model: string | null
  embedding_configured: boolean
  embedding_model: string | null
  vector_store: string
  vector_indexed_count: number
  environment: string
}

export interface AuditLog {
  id: number
  user_id: number | null
  username: string | null
  action: string
  resource_type: string
  resource_id: string | null
  detail: string
  status: string
  created_at: string
}
