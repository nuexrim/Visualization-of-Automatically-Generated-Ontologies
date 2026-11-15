export interface GraphStats {
  V: number
  E: number
  C: number
  mu: number
}

export interface DbInfo {
  name: string
  stats: GraphStats
  /** 불러온 원본 파일 이름과 형식 */
  source?: string
  format?: 'pg_dump' | 'sql' | 'sqlite'
  imported_at?: string
  tables?: number
  warnings?: string[]
}

export interface Column {
  name: string
  type: string
  nullable: boolean
  pk: boolean
  fk: { table: string; column: string } | null
  label: string
  description: string
  value_description: string
}

export interface Table {
  name: string
  row_count: number
  primary_key: string[]
  columns: Column[]
}

export interface ForeignKey {
  name: string
  from_table: string
  from_column: string
  to_table: string
  to_column: string
  composite: boolean
}

export interface Schema {
  db: string
  tables: Table[]
  foreign_keys: ForeignKey[]
  stats: GraphStats
}

// ---------------------------------------------------------------- 온톨로지

export interface Source {
  table: string
  column: string | null
}

export interface Entity {
  iri: string
  name: string
  label: string
  comments: string[]
  /** 코드값 의미 설명 (예: rating 'PG' = ...) */
  value_description: string
  source: Source | null
}

export interface OntClass extends Entity {
  parents: string[]
  external: boolean
}

export interface DataProperty extends Entity {
  domains: string[]
  ranges: string[]
}

export interface ObjectProperty extends Entity {
  domains: string[]
  ranges: string[]
  inverse_of: string[]
}

export interface Triple {
  p: string
  p_iri: string
  o: string
  kind: 'literal' | 'iri' | 'expr'
  o_iri: string | null
  lang: string | null
  datatype: string | null
}

export interface OntologyCounts {
  classes: number
  data_properties: number
  object_properties: number
  triples: number
}

export interface Ontology {
  filename: string
  classes: OntClass[]
  data_properties: DataProperty[]
  object_properties: ObjectProperty[]
  triples: Record<string, Triple[]>
  counts: OntologyCounts
  /** 수정 기록 상태 (생성 중 미리보기에는 없다) */
  history?: EditHistory
}

export interface EditHistory {
  can_undo: boolean
  can_redo: boolean
  /** 마지막 저장 이후 수정 횟수 */
  changes: number
  undo_label: string | null
  redo_label: string | null
}

export interface Issue {
  level: 'error' | 'warning'
  code: string
  iri: string
  message: string
}

/** 수정 연산 (백엔드 backend/ontology/edit.py 참고) */
export type EditOp = { op: string } & Record<string, unknown>

export interface DiffItem {
  iri: string
  name: string
  status: 'added' | 'removed' | 'changed'
  added: [string, string][]
  removed: [string, string][]
}

export interface Diff {
  against: string
  current: string
  unsaved_changes: number
  items: DiffItem[]
  summary: { subjects: number; added: number; removed: number }
}

export interface OntologyFile {
  filename: string
  created_at: string
  kind: string
  note: string
  counts: OntologyCounts
  loaded: boolean
  parent: string | null
  origin: string
}

export type ViewMode = 'erd' | 'onto' | 'split' | 'overlay'

export type Selection =
  | { kind: 'table'; table: string }
  | { kind: 'column'; table: string; column: string }
  | { kind: 'class'; iri: string }
  | { kind: 'objprop'; iri: string }
  | { kind: 'dataprop'; iri: string }

// ---------------------------------------------------------------- 온톨로지 생성 진행 상황

export type GenMode = 'rigor' | 'direct'
export type StepName = 'direct_mapping' | 'context' | 'generate' | 'judge' | 'validate'
export type StepStatus = 'running' | 'done' | 'failed'

export interface StepEvent {
  type: 'step'
  table: string
  step: StepName
  status: StepStatus
  attempt?: number
  detail?: string
  text?: string
  decision?: string
  issues?: { critical: string[]; important: string[]; minor: string[] }
  errors?: string[]
  warnings?: string[]
}

export type GenEvent =
  | { type: 'start'; db: string; order: string[]; mode: GenMode; model: string | null }
  | { type: 'table_start'; table: string; index: number; total: number }
  | StepEvent
  | { type: 'llm_progress'; chars: number }
  | { type: 'llm_retry'; attempt: number; error: string }
  | { type: 'table_done'; table: string; index: number; total: number; outcome: 'enriched' | 'direct_only'; class_iri: string; counts: OntologyCounts; view: Omit<Ontology, 'filename'> }
  | { type: 'done'; file: OntologyFile; outcomes: Record<string, string>; warnings: string[]; usage: { calls: number; input_tokens: number; output_tokens: number } }
  | { type: 'error'; message: string }

export interface GenTable {
  name: string
  status: 'pending' | 'running' | 'done'
  outcome?: 'enriched' | 'direct_only'
  /** (단계, 시도)마다 최신 상태 하나 */
  steps: StepEvent[]
}

export interface GenState {
  mode: GenMode
  model: string | null
  running: boolean
  tables: GenTable[]
  current: string | null
  llmChars: number
  startedAt: number
  finishedAt: number | null
  preview: Ontology | null
  file: OntologyFile | null
  usage: { calls: number; input_tokens: number; output_tokens: number } | null
  error: string | null
}

// ---------------------------------------------------------------- 채팅 (에이전트 실행)

export interface Question {
  id: string
  question: string
  evidence: string
  gold_sql_sqlite: string
  gold_sql_pg: string | null
  gold_status: string
  difficulty: 'easy' | 'medium' | 'hard' | 'extra'
}

export interface ResultTable {
  columns: string[]
  rows: (string | number | boolean | null)[][]
  truncated: boolean
}

/** 캔버스 강조에 쓰는 정보 */
export interface Viz {
  classes?: string[]
  object_properties?: string[]
  data_properties?: string[]
  tables?: string[]
  columns?: { table: string; column: string }[]
  joins?: { left_table: string; left_column: string; right_table: string; right_column: string; fk: { table: string; column: string } | null; via?: 'join' | 'subquery' }[]
}

export type ToolName = 'ontology_query' | 'sql_query'
export interface Tokens {
  input: number
  output: number
}

export type ChatEvent =
  | { type: 'start'; run_id: string; db: string; question: string; evidence: string; use_evidence: boolean; model: string; prompt: string; ontology_file: string }
  | { type: 'thought'; text: string; seconds: number; tokens: Tokens }
  | { type: 'tool_call'; step: number; id: string; tool: ToolName; input: string; seconds: number; tokens: Tokens | null }
  | { type: 'tool_result'; step: number; id: string; tool: ToolName; output: string; ok: boolean; rejected: boolean; seconds: number; table: ResultTable | null; viz: Viz }
  | { type: 'answer'; text: string; final_sql: string | null; table: ResultTable | null; viz: Viz; searched_ontology: boolean; steps: number; seconds: number; seconds_total: number; tokens_total: Tokens }
  | { type: 'error'; message: string; seconds_total?: number; tokens_total?: Tokens }

export interface ChatState {
  running: boolean
  question: string
  events: ChatEvent[]
  /** 저장된 기록을 다시 연 경우 그 기록 id */
  runId?: string
}

/** 저장된 질의 기록 목록의 한 줄 */
export interface RunSummary {
  id: string
  created_at: string | null
  question: string
  ontology_file: string | null
  model: string | null
  status: string
  steps: number
  seconds_total: number | null
  final_sql: string | null
}

/** 경로 재생 상태 */
export interface TraceState {
  /** 보여줄 단계 번호. null 이면 최신 단계를 따라간다 */
  cursor: number | null
  playing: boolean
  /** 강조된 노드로 화면을 자동으로 맞춘다 (사용자가 화면을 움직이면 꺼진다) */
  camera: boolean
  /** 캔버스에 경로를 표시할지 */
  show: boolean
}

export interface AgentPrompt {
  system_prompt: string
  gate_message: string
  model: string | null
  tools: string[]
  limits: { max_steps: number; max_rows: number; sql_timeout_sec: number; max_tokens: number }
}
