import type {
  ApiErrorBody,
  ApiKeyInfo,
  ChatResponse,
  CreatedApiKey,
  DocumentRecord,
  DocumentScope,
  DocumentUpload,
  Identity,
  IndexTask,
  KnowledgeScope,
  LiveHealth,
  Message,
  ReadyHealth,
  Session,
  StreamEvent,
  User,
} from '../types/api'

export const STORAGE_KEYS = {
  apiBase: 'mka.apiBase',
  apiKey: 'mka.apiKey',
  stream: 'mka.stream',
  scope: 'mka.scope',
} as const

const envBase = import.meta.env.VITE_API_BASE || '/api/v1'

export function normalizeApiBase(value: string): string {
  let base = value.trim() || envBase
  base = base.replace(/\/+$/, '')
  if (!/\/api\/v\d+$/i.test(base)) base += '/api/v1'
  return base
}

export function getSavedApiBase(): string {
  return normalizeApiBase(localStorage.getItem(STORAGE_KEYS.apiBase) || envBase)
}

function getApiKey(): string {
  return localStorage.getItem(STORAGE_KEYS.apiKey) || ''
}

function rootUrl(path: string): string {
  const root = getSavedApiBase().replace(/\/api\/v\d+$/i, '')
  return `${root}${path}`
}

export class ApiError extends Error {
  status: number
  code: string
  requestId?: string
  details?: Record<string, unknown>

  constructor(message: string, status = 0, code = 'REQUEST_FAILED', body?: ApiErrorBody) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.requestId = body?.error?.request_id
    this.details = body?.error?.details
  }
}

function validationMessage(detail: ApiErrorBody['detail']): string | null {
  if (typeof detail === 'string') return detail
  if (!Array.isArray(detail)) return null
  return detail.map((item) => item.msg).filter(Boolean).join('；') || null
}

async function parseError(response: Response): Promise<ApiError> {
  let body: ApiErrorBody | undefined
  try {
    body = (await response.json()) as ApiErrorBody
  } catch {
    body = undefined
  }
  const message = body?.error?.message
    || validationMessage(body?.detail)
    || `${response.status} ${response.statusText}`
  return new ApiError(message, response.status, body?.error?.code, body)
}

async function fetchWithErrors(url: string, init: RequestInit = {}): Promise<Response> {
  try {
    const response = await fetch(url, init)
    if (!response.ok) {
      if (response.status === 401) window.dispatchEvent(new Event('mka:unauthorized'))
      throw await parseError(response)
    }
    return response
  } catch (error) {
    if (error instanceof ApiError || (error instanceof DOMException && error.name === 'AbortError')) {
      throw error
    }
    throw new ApiError(error instanceof Error ? error.message : '无法连接到服务', 0, 'NETWORK_ERROR')
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  const key = getApiKey()
  if (key) headers.set('Authorization', `Bearer ${key}`)
  if (init.body && !(init.body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }
  const response = await fetchWithErrors(`${getSavedApiBase()}${path}`, { ...init, headers })
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

function jsonBody(value: unknown): string {
  return JSON.stringify(value)
}

function parseSseFrame(frame: string): StreamEvent | null {
  let event = 'message'
  const data: string[] = []
  for (const rawLine of frame.split(/\r?\n/)) {
    if (!rawLine || rawLine.startsWith(':')) continue
    const separator = rawLine.indexOf(':')
    const field = separator === -1 ? rawLine : rawLine.slice(0, separator)
    let value = separator === -1 ? '' : rawLine.slice(separator + 1)
    if (value.startsWith(' ')) value = value.slice(1)
    if (field === 'event') event = value
    if (field === 'data') data.push(value)
  }
  if (!data.length) return null
  const rawData = data.join('\n')
  try {
    return { event, data: JSON.parse(rawData) as Record<string, unknown> }
  } catch {
    return { event, data: { text: rawData } }
  }
}

async function chatStream(
  query: string,
  sessionId: string | null,
  scope: KnowledgeScope,
  onEvent: (event: StreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const headers = new Headers({
    Accept: 'text/event-stream',
    'Content-Type': 'application/json',
  })
  const key = getApiKey()
  if (key) headers.set('Authorization', `Bearer ${key}`)
  const response = await fetchWithErrors(`${getSavedApiBase()}/chat/stream`, {
    method: 'POST',
    headers,
    body: jsonBody({ query, session_id: sessionId, knowledge_scope: scope }),
    signal,
  })
  if (!response.body) throw new ApiError('浏览器未提供流式响应内容', 0, 'STREAM_UNAVAILABLE')

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  const processFrame = (frame: string) => {
    const parsed = parseSseFrame(frame)
    if (!parsed) return
    onEvent(parsed)
    if (parsed.event === 'error') {
      throw new ApiError(String(parsed.data.message || 'Agent 生成失败'), 500, String(parsed.data.code || 'AGENT_ERROR'))
    }
  }

  while (true) {
    const { value, done } = await reader.read()
    buffer += decoder.decode(value, { stream: !done })
    let match = buffer.match(/\r?\n\r?\n/)
    while (match?.index !== undefined) {
      processFrame(buffer.slice(0, match.index))
      buffer = buffer.slice(match.index + match[0].length)
      match = buffer.match(/\r?\n\r?\n/)
    }
    if (done) break
  }
  if (buffer.trim()) processFrame(buffer)
}

export const api = {
  me: () => request<Identity>('/me'),
  healthLive: async () => (await fetchWithErrors(rootUrl('/health/live'))).json() as Promise<LiveHealth>,
  healthReady: async () => (await fetchWithErrors(rootUrl('/health/ready'))).json() as Promise<ReadyHealth>,
  docsUrl: () => rootUrl('/docs'),

  listUsers: () => request<User[]>('/users'),
  getUser: (id: string) => request<User>(`/users/${encodeURIComponent(id)}`),
  createUser: (name: string, role: 'user' | 'admin') => request<User>('/users', {
    method: 'POST', body: jsonBody({ name, role }),
  }),
  deleteUser: (id: string) => request<void>(`/users/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  listUserKeys: (id: string) => request<ApiKeyInfo[]>(`/users/${encodeURIComponent(id)}/api-keys`),
  createApiKey: (userId: string) => request<CreatedApiKey>('/api-keys', {
    method: 'POST', body: jsonBody({ user_id: userId }),
  }),
  revokeApiKey: (prefix: string) => request<void>(`/api-keys/${encodeURIComponent(prefix)}`, { method: 'DELETE' }),

  listSessions: () => request<Session[]>('/sessions'),
  createSession: (title?: string | null) => request<Session>('/sessions', {
    method: 'POST', body: jsonBody({ title: title || null }),
  }),
  getMessages: (sessionId: string) => request<Message[]>(`/sessions/${encodeURIComponent(sessionId)}/messages`),
  deleteSession: (sessionId: string) => request<void>(`/sessions/${encodeURIComponent(sessionId)}`, { method: 'DELETE' }),

  chat: (query: string, sessionId: string | null, scope: KnowledgeScope, signal?: AbortSignal) => request<ChatResponse>('/chat', {
    method: 'POST', body: jsonBody({ query, session_id: sessionId, knowledge_scope: scope }), signal,
  }),
  chatStream,

  listDocuments: () => request<DocumentRecord[]>('/documents'),
  getDocument: (id: string) => request<DocumentRecord>(`/documents/${encodeURIComponent(id)}`),
  uploadDocument: (file: File, scope: DocumentScope) => {
    const form = new FormData()
    form.append('file', file)
    form.append('scope', scope)
    return request<DocumentUpload>('/documents', { method: 'POST', body: form })
  },
  deleteDocument: (id: string) => request<void>(`/documents/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  getTask: (id: string) => request<IndexTask>(`/tasks/${encodeURIComponent(id)}`),
  downloadDocument: async (id: string, filename: string) => {
    const headers = new Headers()
    const key = getApiKey()
    if (key) headers.set('Authorization', `Bearer ${key}`)
    const response = await fetchWithErrors(`${getSavedApiBase()}/documents/${encodeURIComponent(id)}/download`, { headers })
    const blobUrl = URL.createObjectURL(await response.blob())
    const link = document.createElement('a')
    link.href = blobUrl
    link.download = filename
    document.body.appendChild(link)
    link.click()
    link.remove()
    URL.revokeObjectURL(blobUrl)
  },
}
