export type Role = 'user' | 'admin'
export type KnowledgeScope = 'private' | 'shared' | 'hybrid'
export type DocumentScope = 'private' | 'shared'
export type SessionType = 'chat' | 'multi_agent'

export interface Identity {
  user_id: string
  name: string
  role: Role
  api_key_prefix: string
}

export interface User {
  user_id: string
  name: string
  role: Role
  created_at: string
}

export interface ApiKeyInfo {
  prefix: string
  user_id: string
  created_at: string
  revoked_at: string | null
}

export interface CreatedApiKey {
  key: string
  prefix: string
  created_at: string
}

export interface Session {
  session_id: string
  session_type: SessionType
  title: string | null
  message_count: number
  created_at: string
  updated_at: string
}

export interface Citation {
  index: number
  document_name: string
  scope: DocumentScope
  page: number | null
  section: string | null
  text_snippet: string
}

export interface TokenUsage {
  input_tokens: number
  output_tokens: number
  total_tokens: number
}

export interface Message {
  role: 'user' | 'assistant'
  content: string
  created_at: string
  citations?: Citation[]
  token_usage?: TokenUsage | null
  state?: 'sending' | 'streaming' | 'complete' | 'error'
  error_message?: string
}

export interface ChatResponse {
  answer: string
  session_id: string
  citations: Citation[]
  token_usage: TokenUsage | null
}

export interface DocumentRecord {
  document_id: string
  filename: string
  mime_type: string
  file_size: number
  scope: DocumentScope
  status: 'uploaded' | 'queued' | 'parsing' | 'chunking' | 'embedding' | 'indexed' | 'failed' | string
  chunk_count: number
  error_message: string | null
  created_at: string
  updated_at: string
}

export type DocumentStatusFilter = 'indexed' | 'processing' | 'failed'

export interface DocumentListParams {
  page?: number
  pageSize?: number
  search?: string
  scope?: DocumentScope
  status?: DocumentStatusFilter
}

export interface DocumentPage {
  items: DocumentRecord[]
  total: number
  page: number
  page_size: number
  total_pages: number
}

export interface DocumentUpload {
  document_id: string
  filename: string
  mime_type: string
  file_size: number
  scope: DocumentScope
  status: string
  task_id: string
  created_at: string
}

export interface DocumentBatchUploadItem {
  filename: string
  success: boolean
  document: DocumentUpload | null
  error_code: string | null
  error_message: string | null
}

export interface DocumentBatchUpload {
  total: number
  succeeded: number
  failed: number
  results: DocumentBatchUploadItem[]
}

export interface IndexTask {
  task_id: string
  document_id: string
  status: 'queued' | 'parsing' | 'chunking' | 'done' | 'failed' | string
  progress: number
  error_message: string | null
  created_at: string
  updated_at: string
}

export interface ReadyHealth {
  status: string
  checks: Record<'chat_agent' | 'multi_agent' | 'embedding' | 'milvus' | 'retrieval', string>
}

export interface LiveHealth {
  status: string
}

export interface ApiErrorBody {
  error?: {
    code?: string
    message?: string
    request_id?: string
    details?: Record<string, unknown>
  }
  detail?: string | Array<{ msg?: string; loc?: Array<string | number> }>
}

export interface StreamEvent {
  event: 'start' | 'token' | 'done' | 'error' | string
  data: Record<string, unknown>
}
