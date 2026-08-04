/* ═══════════════════════════════════════════════════════════════════
   API Layer — all HTTP communication with the backend
   ═══════════════════════════════════════════════════════════════════ */

const BASE = () => {
  const saved = localStorage.getItem('mka_base')
  return (saved || '/api/v1').replace(/\/+$/, '')
}

function rootUrl(path) {
  // Derive root URL by stripping /api/vN suffix
  const base = BASE().replace(/\/+$/, '')
  const root = base.replace(/\/api\/v\d+$/, '').replace(/\/+$/, '')
  return root + path
}

function key() {
  return localStorage.getItem('mka_key') || ''
}

async function request(method, path, body, ct = 'application/json') {
  const headers = {}
  if (ct) headers['Content-Type'] = ct
  const k = key()
  if (k) headers['Authorization'] = 'Bearer ' + k

  const opts = { method, headers }
  if (body && ct) opts.body = ct === 'application/json' ? JSON.stringify(body) : body

  const res = await fetch(BASE() + path, opts)
  if (!res.ok) {
    let msg = `${res.status} ${res.statusText}`
    try { const e = await res.json(); msg = e.error?.message || e.detail || msg } catch (_) {}
    throw new Error(msg)
  }
  if (res.status === 204) return null
  return res.json()
}

async function requestRaw(path) {
  const headers = {}
  const k = key()
  if (k) headers['Authorization'] = 'Bearer ' + k
  const res = await fetch(BASE() + path, { headers })
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return res
}

// ── Auth / Users ──
export const api = {
  me:       ()              => request('GET', '/me'),
  health:   ()              => fetch(rootUrl('/health/ready')).then(r => r.json()).catch(() => null),

  // Users (admin)
  listUsers:    ()              => request('GET', '/users'),
  createUser:   (name, role)    => request('POST', '/users', { name, role }),
  getUser:      (id)            => request('GET', `/users/${id}`),
  deleteUser:   (id)            => request('DELETE', `/users/${id}`),
  listUserKeys: (id)            => request('GET', `/users/${id}/api-keys`),
  createKey:    (userId)        => request('POST', '/api-keys', { user_id: userId }),
  revokeKey:    (prefix)        => request('DELETE', `/api-keys/${encodeURIComponent(prefix)}`),

  // Sessions
  listSessions:   ()          => request('GET', '/sessions'),
  createSession:  (title)     => request('POST', '/sessions', { title: title || null }),
  getMessages:    (sid)       => request('GET', `/sessions/${sid}/messages`),
  deleteSession:  (sid)       => request('DELETE', `/sessions/${sid}`),

  // Chat
  chat: (query, sessionId, scope) =>
    request('POST', '/chat', { query, session_id: sessionId, knowledge_scope: scope }),

  chatStream: async function* (query, sessionId, scope) {
    const headers = { 'Content-Type': 'application/json', 'Accept': 'text/event-stream' }
    const k = key()
    if (k) headers['Authorization'] = 'Bearer ' + k
    const res = await fetch(BASE() + '/chat/stream', {
      method: 'POST', headers,
      body: JSON.stringify({ query, session_id: sessionId, knowledge_scope: scope }),
    })
    if (!res.ok) {
      let msg = `${res.status}`
      try { const e = await res.json(); msg = e.error?.message || e.detail || msg } catch (_) {}
      throw new Error(msg)
    }
    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    let buf = ''
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buf += decoder.decode(value, { stream: true })
      const lines = buf.split('\n')
      buf = lines.pop()
      for (const line of lines) {
        if (line.startsWith('data: ')) {
          try { yield JSON.parse(line.slice(6)) } catch (_) {}
        }
      }
    }
    if (buf.startsWith('data: ')) {
      try { yield JSON.parse(buf.slice(6)) } catch (_) {}
    }
  },

  // Documents
  listDocs:   ()          => request('GET', '/documents'),
  getDoc:     (id)        => request('GET', `/documents/${id}`),
  deleteDoc:  (id)        => request('DELETE', `/documents/${id}`),
  getTask:    (id)        => request('GET', `/tasks/${id}`),

  uploadDoc: async (file, scope) => {
    const form = new FormData()
    form.append('file', file)
    form.append('scope', scope)
    const headers = {}
    const k = key()
    if (k) headers['Authorization'] = 'Bearer ' + k
    const res = await fetch(BASE() + '/documents', { method: 'POST', headers, body: form })
    if (!res.ok) {
      let msg = res.statusText
      try { const e = await res.json(); msg = e.error?.message || e.detail || msg } catch (_) {}
      throw new Error(msg)
    }
    return res.json()
  },

  downloadDoc: async (id, filename) => {
    const res = await requestRaw(`/documents/${id}/download`)
    const blob = await res.blob()
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url; a.download = filename
    document.body.appendChild(a); a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  },
}
