import { create } from 'zustand'
import { api } from './api'
import type { ChatEvent, ChatState, EditOp, Issue, RunSummary, TraceState, Column, DbInfo, GenEvent, GenMode, GenState, Ontology, OntologyFile, Question, Schema, Selection, StepEvent, ViewMode } from './types'

export interface Tip {
  x: number
  y: number
  table: string
  column: Column
}

export interface Notice {
  kind: 'info' | 'error'
  text: string
  /** 방금 생성한 파일이면 "불러오기" 버튼을 함께 보여준다 */
  file?: string
}

interface State {
  dbs: DbInfo[]
  db: string | null
  schema: Schema | null
  loading: boolean
  error: string | null
  /** 불러오는 중인 DB 파일 이름 */
  importing: string | null

  ontology: Ontology | null
  files: OntologyFile[]
  view: ViewMode
  /** 온톨로지 생성 진행 상황. 생성 중이거나 결과를 아직 닫지 않았으면 값이 있다 */
  gen: GenState | null
  filesOpen: boolean
  notice: Notice | null

  /** BIRD 예시 질문 (이 DB에 해당하는 것이 있을 때만) */
  questions: Question[]
  /** 마지막으로 실행한(또는 실행 중인) 질문 */
  chat: ChatState | null
  trace: TraceState
  runs: RunSummary[]
  /** 마지막 검사 결과 (수정·저장할 때마다 갱신) */
  issues: Issue[]
  /** 수정 중인 요청이 있다 */
  editing: boolean
  diffOpen: boolean

  selection: Selection | null
  tip: Tip | null
  /** 값이 바뀔 때마다 캔버스가 해당 동작을 한 번 수행한다 */
  fitSignal: number
  relayoutSignal: number

  init: () => Promise<void>
  selectDb: (db: string) => Promise<void>
  importDb: (file: File) => Promise<void>
  closeDb: () => Promise<void>
  select: (selection: Selection | null) => void
  setTip: (tip: Tip | null) => void
  setView: (view: ViewMode) => void
  fit: () => void
  relayout: () => void

  generate: (mode: GenMode) => Promise<void>
  stopGenerate: () => void
  closeGen: () => void
  refreshFiles: () => Promise<void>
  loadFile: (filename: string) => Promise<void>
  uploadFile: (file: File) => Promise<void>
  unload: () => Promise<void>
  setFilesOpen: (open: boolean) => void
  setNotice: (notice: Notice | null) => void

  ask: (question: string, evidence: string, useEvidence: boolean) => Promise<void>
  stopChat: () => void
  setTrace: (patch: Partial<TraceState>) => void
  refreshRuns: () => Promise<void>
  openRun: (id: string) => Promise<void>

  /** 온톨로지 수정. 성공하면 true. 검사에 걸리면 이유를 알림으로 보여주고 false */
  edit: (ops: EditOp[]) => Promise<boolean>
  undo: () => Promise<void>
  redo: () => Promise<void>
  saveVersion: (note: string) => Promise<void>
  refreshIssues: () => Promise<void>
  setDiffOpen: (open: boolean) => void
}

const TRACE0: TraceState = { cursor: null, playing: false, camera: true, show: true }

const LAST_DB_KEY = 'ontolens:last-db'
const message = (e: unknown) => (e instanceof Error ? e.message : String(e))

/** 생성 중 미리보기 온톨로지의 파일 이름 자리 */
export const PREVIEW = '(생성 중)'
let abort: AbortController | null = null
let viewBefore: ViewMode = 'erd'
let chatAbort: AbortController | null = null

function upsertStep(steps: StepEvent[], e: StepEvent): StepEvent[] {
  const i = steps.findIndex((s) => s.step === e.step && s.attempt === e.attempt)
  return i < 0 ? [...steps, e] : steps.map((s, j) => (j === i ? { ...s, ...e } : s))
}

/** 되돌리기 등으로 선택한 요소가 사라졌으면 선택을 푼다 */
function keepSelection(sel: Selection | null, o: Ontology): Selection | null {
  if (!sel || !('iri' in sel)) return sel
  const list = sel.kind === 'class' ? o.classes : sel.kind === 'objprop' ? o.object_properties : o.data_properties
  return list.some((x) => x.iri === sel.iri) ? sel : null
}

/** 화면에 보여줄 온톨로지: 생성 중이면 지금까지 만들어진 부분, 아니면 불러온 파일 */
export const shownOntology = (s: { gen: GenState | null; ontology: Ontology | null }): Ontology | null => (s.gen ? s.gen.preview : s.ontology)

export const useStore = create<State>((set, get) => ({
  dbs: [],
  db: null,
  schema: null,
  loading: false,
  error: null,
  importing: null,
  ontology: null,
  files: [],
  view: 'erd',
  gen: null,
  filesOpen: false,
  notice: null,
  questions: [],
  chat: null,
  trace: TRACE0,
  runs: [],
  issues: [],
  editing: false,
  diffOpen: false,
  selection: null,
  tip: null,
  fitSignal: 0,
  relayoutSignal: 0,

  init: async () => {
    try {
      const dbs = await api.dbs()
      set({ dbs })
      const last = localStorage.getItem(LAST_DB_KEY)
      const first = dbs.find((d) => d.name === last) ?? dbs[0]
      if (first) await get().selectDb(first.name)
    } catch (e) {
      set({ error: `백엔드에 연결하지 못했습니다: ${message(e)}` })
    }
  },

  selectDb: async (db) => {
    abort?.abort()
    chatAbort?.abort()
    set({ db, loading: true, error: null, selection: null, tip: null, notice: null, filesOpen: false, gen: null, chat: null, trace: TRACE0, runs: [], questions: [] })
    try {
      const [schema, ontology, files, questions] = await Promise.all([api.schema(db), api.ontology(db), api.ontologyFiles(db), api.questions(db)])
      if (get().db !== db) return // 그 사이 다른 DB를 골랐다
      localStorage.setItem(LAST_DB_KEY, db)
      // 불러온 온톨로지가 없으면 ERD만 보인다
      set({ schema, ontology, files, questions, loading: false, view: ontology ? get().view : 'erd' })
      void get().refreshRuns()
      if (ontology) void get().refreshIssues()
    } catch (e) {
      set({ loading: false, error: `스키마를 불러오지 못했습니다: ${message(e)}` })
    }
  },

  importDb: async (file) => {
    if (get().importing || get().gen?.running) return
    set({ importing: file.name, notice: null, error: null })
    try {
      let info
      try {
        info = await api.importDb(file, false)
      } catch (e) {
        if ((e as { status?: number }).status !== 409) throw e
        // 같은 이름의 DB가 이미 있다: 바꿀지 사용자에게 묻는다
        if (!window.confirm(`${message(e)}\n이 파일로 바꿀까요? (기존 DB는 지워지고, 만들어 둔 온톨로지 파일은 남습니다)`)) return
        info = await api.importDb(file, true)
      }
      set({ dbs: await api.dbs() })
      await get().selectDb(info.name)
      const warn = info.warnings?.length ? ` · 복원 중 경고 ${info.warnings.length}건: ${info.warnings[0]}` : ''
      set({ notice: { kind: 'info', text: `${file.name} 을(를) 읽어 ERD를 만들었습니다 (테이블 ${info.stats.V}개, 외래 키 연결 ${info.stats.E}쌍)${warn}` } })
    } catch (e) {
      set({ notice: { kind: 'error', text: `DB 불러오기 실패: ${message(e)}` } })
    } finally {
      set({ importing: null })
    }
  },

  closeDb: async () => {
    const db = get().db
    if (!db || get().gen?.running) return
    if (!window.confirm(`'${db}' DB를 닫을까요?\nPostgreSQL에서 지워집니다. 원본 파일과 만들어 둔 온톨로지 파일은 남고, 파일을 다시 불러오면 복구됩니다.`)) return
    try {
      abort?.abort()
      await api.deleteDb(db)
      const dbs = await api.dbs()
      localStorage.removeItem(LAST_DB_KEY)
      set({ dbs, db: null, schema: null, ontology: null, files: [], gen: null, selection: null, view: 'erd', notice: null })
      if (dbs[0]) await get().selectDb(dbs[0].name)
    } catch (e) {
      set({ notice: { kind: 'error', text: `DB 닫기 실패: ${message(e)}` } })
    }
  },

  select: (selection) => set({ selection }),
  setTip: (tip) => set({ tip }),
  setView: (view) => set({ view: get().ontology || get().gen ? view : 'erd' }),
  fit: () => set((s) => ({ fitSignal: s.fitSignal + 1 })),
  relayout: () => set((s) => ({ relayoutSignal: s.relayoutSignal + 1 })),

  generate: async (mode) => {
    const db = get().db
    if (!db || get().gen?.running) return
    abort = new AbortController()
    viewBefore = get().view
    set({
      notice: null,
      selection: null,
      view: 'split',
      gen: { mode, model: null, running: true, tables: [], current: null, llmChars: 0, startedAt: Date.now(), finishedAt: null, preview: null, file: null, usage: null, error: null },
    })
    const patch = (f: (g: GenState) => Partial<GenState>) => set((s) => (s.gen ? { gen: { ...s.gen, ...f(s.gen) } } : {}))
    const onEvent = (e: GenEvent) => {
      if (get().db !== db) return
      switch (e.type) {
        case 'start':
          patch(() => ({ model: e.model, tables: e.order.map((name) => ({ name, status: 'pending', steps: [] })) }))
          break
        case 'table_start':
          patch((g) => ({ current: e.table, llmChars: 0, tables: g.tables.map((t) => (t.name === e.table ? { ...t, status: 'running' } : t)) }))
          set({ selection: { kind: 'table', table: e.table } }) // 처리 중인 테이블을 ERD에서 강조
          break
        case 'step':
          patch((g) => ({ llmChars: 0, tables: g.tables.map((t) => (t.name === e.table ? { ...t, steps: upsertStep(t.steps, e) } : t)) }))
          break
        case 'llm_progress':
          patch(() => ({ llmChars: e.chars }))
          break
        case 'table_done':
          patch((g) => ({
            preview: { filename: PREVIEW, ...e.view },
            tables: g.tables.map((t) => (t.name === e.table ? { ...t, status: 'done', outcome: e.outcome } : t)),
          }))
          break
        case 'done':
          patch(() => ({ running: false, finishedAt: Date.now(), current: null, file: e.file, usage: e.usage }))
          set({ selection: null })
          void get().refreshFiles()
          break
        case 'error':
          patch(() => ({ running: false, finishedAt: Date.now(), error: e.message }))
          break
      }
    }
    try {
      await api.generateOntology(db, mode, onEvent, abort.signal)
      // 스트림이 done/error 없이 끊긴 경우
      if (get().gen?.running) patch(() => ({ running: false, finishedAt: Date.now(), error: '서버와의 연결이 끊겼습니다.' }))
    } catch (e) {
      const stopped = e instanceof DOMException && e.name === 'AbortError'
      patch(() => ({ running: false, finishedAt: Date.now(), error: stopped ? '사용자가 중지했습니다.' : message(e) }))
    }
  },

  stopGenerate: () => abort?.abort(),

  closeGen: () => {
    if (get().gen?.running) return
    set({ gen: null, selection: null, view: get().ontology ? viewBefore : 'erd' })
  },

  refreshFiles: async () => {
    const db = get().db
    if (!db) return
    const files = await api.ontologyFiles(db)
    if (get().db === db) set({ files })
  },

  loadFile: async (filename) => {
    const db = get().db
    if (!db) return
    try {
      const ontology = await api.loadOntology(db, filename)
      if (get().db !== db) return
      const wasErd = get().view === 'erd'
      set({ ontology, selection: null, filesOpen: false, notice: null, gen: null, view: wasErd || get().gen ? 'onto' : get().view })
      await get().refreshFiles()
      void get().refreshIssues()
    } catch (e) {
      set({ notice: { kind: 'error', text: `불러오기 실패: ${message(e)}` } })
    }
  },

  uploadFile: async (file) => {
    const db = get().db
    if (!db) return
    try {
      const info = await api.uploadOntology(db, file)
      set({ notice: { kind: 'info', text: `업로드했습니다: ${info.filename}`, file: info.filename } })
      await get().refreshFiles()
    } catch (e) {
      set({ notice: { kind: 'error', text: `업로드 실패: ${message(e)}` } })
    }
  },

  unload: async () => {
    const db = get().db
    if (!db) return
    await api.unloadOntology(db)
    chatAbort?.abort()
    set({ ontology: null, view: 'erd', selection: null, chat: null, trace: TRACE0, issues: [] })
    await get().refreshFiles()
  },

  setFilesOpen: (filesOpen) => {
    set({ filesOpen })
    if (filesOpen) void get().refreshFiles()
  },
  setNotice: (notice) => set({ notice }),

  ask: async (question, evidence, useEvidence) => {
    const db = get().db
    if (!db || !question.trim() || get().chat?.running) return
    chatAbort = new AbortController()
    // 경로를 보려면 온톨로지와 ERD가 함께 보여야 한다
    set({ chat: { running: true, question: question.trim(), events: [] }, trace: TRACE0, selection: null, view: get().view === 'overlay' ? 'overlay' : 'split' })
    const push = (e: ChatEvent) => set((s) => (s.chat && s.db === db ? { chat: { ...s.chat, events: [...s.chat.events, e] } } : {}))
    try {
      await api.chat(db, { question, evidence, use_evidence: useEvidence }, push, chatAbort.signal)
    } catch (e) {
      const stopped = e instanceof DOMException && e.name === 'AbortError'
      push({ type: 'error', message: stopped ? '사용자가 중지했습니다.' : message(e) })
    } finally {
      set((s) => (s.chat ? { chat: { ...s.chat, running: false } } : {}))
      void get().refreshRuns()
    }
  },

  stopChat: () => chatAbort?.abort(),

  edit: async (ops) => {
    const db = get().db
    if (!db || !get().ontology || get().editing) return false
    set({ editing: true })
    try {
      const res = await api.patchOntology(db, ops)
      if (get().db !== db) return false
      const { issues, applied, ...ontology } = res
      // 이름을 바꿨으면 선택도 새 IRI로 옮긴다
      const sel = get().selection
      const renamed = ops.find((o) => o.op === 'rename')
      const selection = renamed && sel && 'iri' in sel && sel.iri === renamed.iri ? { ...sel, iri: `http://example.org/ontology#${String(renamed.name)}` } : sel
      set({ ontology, issues, selection, notice: { kind: 'info', text: `수정했습니다: ${applied}. 다음 질문부터 에이전트가 바로 사용합니다.` } })
      return true
    } catch (e) {
      const issues = (e as { issues?: Issue[] }).issues
      set({ notice: { kind: 'error', text: issues?.length ? `${message(e)} ${issues.map((i) => i.message).join(' / ')}` : `수정 실패: ${message(e)}` } })
      return false
    } finally {
      set({ editing: false })
    }
  },

  undo: async () => {
    const db = get().db
    if (!db || !get().ontology?.history?.can_undo || get().editing) return
    set({ editing: true })
    try {
      const label = get().ontology?.history?.undo_label
      const ontology = await api.undo(db)
      set({ ontology, selection: keepSelection(get().selection, ontology), notice: { kind: 'info', text: `되돌렸습니다: ${label}` } })
      void get().refreshIssues()
    } catch (e) {
      set({ notice: { kind: 'error', text: `되돌리기 실패: ${message(e)}` } })
    } finally {
      set({ editing: false })
    }
  },

  redo: async () => {
    const db = get().db
    if (!db || !get().ontology?.history?.can_redo || get().editing) return
    set({ editing: true })
    try {
      const label = get().ontology?.history?.redo_label
      const ontology = await api.redo(db)
      set({ ontology, selection: keepSelection(get().selection, ontology), notice: { kind: 'info', text: `다시 했습니다: ${label}` } })
      void get().refreshIssues()
    } catch (e) {
      set({ notice: { kind: 'error', text: `다시하기 실패: ${message(e)}` } })
    } finally {
      set({ editing: false })
    }
  },

  saveVersion: async (note) => {
    const db = get().db
    if (!db || !get().ontology) return
    try {
      const res = await api.saveOntology(db, note)
      set({ ontology: res.ontology, issues: res.issues, notice: { kind: 'info', text: `새 버전으로 저장했습니다: ${res.file.filename}` } })
      await get().refreshFiles()
    } catch (e) {
      const issues = (e as { issues?: Issue[] }).issues
      set({ notice: { kind: 'error', text: `저장 실패: ${message(e)}${issues?.length ? ' ' + issues.map((i) => i.message).join(' / ') : ''}` } })
    }
  },

  refreshIssues: async () => {
    const db = get().db
    if (!db || !get().ontology) return
    try {
      const issues = await api.checkOntology(db)
      if (get().db === db) set({ issues })
    } catch {
      /* 검사 결과는 없어도 화면에 지장이 없다 */
    }
  },

  setDiffOpen: (diffOpen) => set({ diffOpen }),

  setTrace: (patch) => set((s) => ({ trace: { ...s.trace, ...patch } })),

  refreshRuns: async () => {
    const db = get().db
    if (!db) return
    try {
      const runs = await api.runs(db)
      if (get().db === db) set({ runs })
    } catch {
      /* 기록 목록은 없어도 동작에 지장이 없다 */
    }
  },

  openRun: async (id) => {
    const db = get().db
    if (!db || get().chat?.running) return
    try {
      const run = await api.run(db, id)
      if (get().db !== db) return
      // 처음 단계부터 재생할 수 있게 첫 단계에 멈춰 둔다
      set({ chat: { running: false, question: run.question, events: run.events, runId: run.id }, trace: { ...TRACE0, cursor: 0 }, selection: null, view: get().ontology ? (get().view === 'overlay' ? 'overlay' : 'split') : 'erd' })
    } catch (e) {
      set({ notice: { kind: 'error', text: `기록을 열지 못했습니다: ${message(e)}` } })
    }
  },
}))
