import type { AgentPrompt, ChatEvent, Diff, EditOp, Issue, RunSummary, DbInfo, GenEvent, GenMode, Ontology, OntologyFile, Question, Schema } from './types'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init)
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`
    try {
      const body = (await res.json()) as { detail?: unknown }
      if (typeof body.detail === 'string') detail = body.detail
      // 검사 실패(422): {message, issues}
      else if (body.detail && typeof body.detail === 'object' && 'message' in body.detail) {
        const d = body.detail as { message: string; issues?: Issue[] }
        throw Object.assign(new Error(d.message), { status: res.status, issues: d.issues ?? [] })
      }
    } catch (e) {
      if ((e as { issues?: unknown }).issues) throw e
      /* 본문이 JSON이 아니면 상태 코드만 쓴다 */
    }
    throw Object.assign(new Error(detail), { status: res.status })
  }
  return res.json() as Promise<T>
}

/** SSE 응답을 읽어 이벤트마다 onEvent 를 부른다. */
async function readSse<E>(path: string, init: RequestInit, onEvent: (e: E) => void): Promise<void> {
  const res = await fetch(path, init)
  if (!res.ok || !res.body) {
    const body = (await res.json().catch(() => ({}))) as { detail?: string }
    throw new Error(typeof body.detail === 'string' ? body.detail : `${res.status} ${res.statusText}`)
  }
  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader()
  let buffer = ''
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += value
    let end: number
    while ((end = buffer.indexOf('\n\n')) >= 0) {
      const chunk = buffer.slice(0, end)
      buffer = buffer.slice(end + 2)
      for (const line of chunk.split('\n')) if (line.startsWith('data: ')) onEvent(JSON.parse(line.slice(6)) as E)
    }
  }
}

const json = (body: unknown): RequestInit => ({ method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })

export const api = {
  dbs: () => request<DbInfo[]>('/api/dbs'),
  /** DB 파일을 올려 PostgreSQL에 불러온다. 같은 이름이 있으면 409 */
  importDb: (file: File, replace: boolean) => {
    const form = new FormData()
    form.append('file', file)
    form.append('replace', String(replace))
    return request<DbInfo>('/api/dbs/import', { method: 'POST', body: form })
  },
  deleteDb: (db: string) => request<{ ok: boolean }>(`/api/dbs/${db}`, { method: 'DELETE' }),
  schema: (db: string) => request<Schema>(`/api/dbs/${db}/schema`),
  /** 불러온 온톨로지가 없으면 null */
  ontology: (db: string) =>
    request<Ontology>(`/api/dbs/${db}/ontology`).catch((e: Error & { status?: number }) => {
      if (e.status === 404) return null
      throw e
    }),
  ontologyFiles: (db: string) => request<OntologyFile[]>(`/api/dbs/${db}/ontology/files`),
  /** 온톨로지 생성. 진행 상황이 SSE로 온다. */
  generateOntology: (db: string, mode: GenMode, onEvent: (e: GenEvent) => void, signal: AbortSignal) =>
    readSse(`/api/dbs/${db}/ontology/generate?mode=${mode}`, { method: 'POST', signal }, onEvent),
  questions: (db: string) => request<Question[]>(`/api/dbs/${db}/questions`),
  agentPrompt: () => request<AgentPrompt>('/api/agent/prompt'),
  /** 질문 실행. 에이전트의 각 단계가 SSE로 온다. */
  chat: (db: string, body: { question: string; evidence: string; use_evidence: boolean }, onEvent: (e: ChatEvent) => void, signal: AbortSignal) =>
    readSse(`/api/dbs/${db}/chat`, { ...json(body), signal }, onEvent),
  runs: (db: string) => request<RunSummary[]>(`/api/dbs/${db}/chat/runs`),
  run: (db: string, id: string) => request<{ id: string; question: string; ontology_file: string | null; events: ChatEvent[] }>(`/api/dbs/${db}/chat/runs/${id}`),
  patchOntology: (db: string, ops: EditOp[]) =>
    request<Ontology & { issues: Issue[]; applied: string }>(`/api/dbs/${db}/ontology`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ops }) }),
  undo: (db: string) => request<Ontology>(`/api/dbs/${db}/ontology/undo`, { method: 'POST' }),
  redo: (db: string) => request<Ontology>(`/api/dbs/${db}/ontology/redo`, { method: 'POST' }),
  checkOntology: (db: string) => request<Issue[]>(`/api/dbs/${db}/ontology/check`),
  saveOntology: (db: string, note: string) => request<{ file: OntologyFile; ontology: Ontology; issues: Issue[] }>(`/api/dbs/${db}/ontology/save`, json({ note })),
  versions: (db: string) => request<OntologyFile[]>(`/api/dbs/${db}/ontology/versions`),
  diff: (db: string, against?: string) => request<Diff>(`/api/dbs/${db}/ontology/diff${against ? `?against=${encodeURIComponent(against)}` : ''}`),
  loadOntology: (db: string, filename: string) => request<Ontology>(`/api/dbs/${db}/ontology/load`, json({ filename })),
  unloadOntology: (db: string) => request<{ ok: boolean }>(`/api/dbs/${db}/ontology`, { method: 'DELETE' }),
  uploadOntology: (db: string, file: File) => {
    const form = new FormData()
    form.append('file', file)
    return request<OntologyFile>(`/api/dbs/${db}/ontology/upload`, { method: 'POST', body: form })
  },
}
