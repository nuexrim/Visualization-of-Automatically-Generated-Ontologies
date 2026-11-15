/** 질의 경로 재생: 에이전트 이벤트를 "단계(frame)"로 나누고, 단계마다 캔버스에 강조할 것을 계산한다. */
import { useMemo } from 'react'
import { columnKey, useHighlight, useOntologyIndex, type Highlight, type OntologyIndex } from './links'
import { useStore } from './store'
import type { ChatEvent, ToolName, Viz } from './types'

type Result = Extract<ChatEvent, { type: 'tool_result' }>
type Answer = Extract<ChatEvent, { type: 'answer' }>
export type Join = NonNullable<Viz['joins']>[number]

export interface Frame {
  kind: 'tool' | 'answer'
  /** 실행 기록에 보이는 번호 (도구 호출 step, 답변은 마지막) */
  label: string
  tool: ToolName | null
  input: string | null
  result: Result | null
  answer: Answer | null
  /** 이 단계가 끝나 결과가 있는가 */
  done: boolean
}

export function buildFrames(events: ChatEvent[]): Frame[] {
  const results = new Map(events.filter((e): e is Result => e.type === 'tool_result').map((e) => [e.id, e]))
  const frames: Frame[] = []
  for (const e of events) {
    if (e.type === 'tool_call') {
      const r = results.get(e.id) ?? null
      frames.push({ kind: 'tool', label: String(e.step), tool: e.tool, input: e.input, result: r, answer: null, done: r !== null })
    } else if (e.type === 'answer') {
      frames.push({ kind: 'answer', label: '답변', tool: null, input: e.final_sql, result: null, answer: e, done: true })
    }
  }
  return frames
}

/** 경로 강조. 선택 강조(Highlight)에 "지금 단계"와 조인 정보를 더한 것. */
export interface TraceHighlight extends Highlight {
  /** 지금 단계에서 새로 강조된 것 (빛나는 효과) */
  now: { classes: Set<string>; props: Set<string>; tables: Set<string>; columns: Set<string> }
  /** 객체 속성 화살표 애니메이션 순서 */
  propOrder: Map<string, number>
  /** SQL 조인 (외래 키와 일치하면 fk 가 있다) */
  joins: Join[]
  /** 지금 단계가 SQL이면 조인 경로를 애니메이션한다 */
  joinsNow: boolean
}

const emptySets = () => ({ classes: new Set<string>(), props: new Set<string>(), tables: new Set<string>(), columns: new Set<string>() })

/** 한 단계의 강조 항목: 온톨로지 검색은 결과에 나온 클래스·속성과 그 출처, SQL은 조인 경로와 대응 클래스 */
function frameItems(f: Frame, idx: OntologyIndex | null) {
  const s = { ...emptySets(), order: [] as string[], joins: [] as Join[] }
  const viz: Viz | undefined = f.answer?.viz ?? (f.result?.ok ? f.result.viz : undefined)
  if (!viz) return s
  const addClass = (iri: string) => {
    s.classes.add(iri)
    const t = idx?.classByIri.get(iri)?.source?.table
    if (t) s.tables.add(t)
  }
  viz.classes?.forEach(addClass)
  for (const iri of viz.object_properties ?? []) {
    s.props.add(iri)
    s.order.push(iri)
    // 화살표 양 끝 클래스도 함께 보여야 경로가 보인다
    const p = idx?.objProp.get(iri)
    p?.domains.forEach(addClass)
    p?.ranges.forEach(addClass)
  }
  for (const iri of viz.data_properties ?? []) {
    s.props.add(iri)
    idx?.dataProp.get(iri)?.domains.forEach(addClass)
  }
  viz.tables?.forEach((t) => s.tables.add(t))
  viz.columns?.forEach((c) => s.columns.add(columnKey(c.table, c.column)))
  for (const j of viz.joins ?? []) {
    s.joins.push(j)
    s.columns.add(columnKey(j.left_table, j.left_column))
    s.columns.add(columnKey(j.right_table, j.right_column))
  }
  // SQL 단계: 사용한 테이블에 대응하는 클래스, 외래 키 조인에 대응하는 객체 속성도 온톨로지 쪽에 표시
  if (f.tool === 'sql_query' || f.kind === 'answer') {
    for (const t of viz.tables ?? []) idx?.classesByTable.get(t)?.forEach((c) => s.classes.add(c.iri))
    for (const j of viz.joins ?? []) {
      if (!j.fk) continue
      const hit = idx?.propByColumn.get(columnKey(j.fk.table, j.fk.column))
      if (hit?.kind === 'objprop') {
        s.props.add(hit.iri)
        s.order.push(hit.iri)
      }
    }
  }
  return s
}

/**
 * cursor 단계까지 누적한 강조. 지난 단계에서 찾은 것은 흐리게 하지 않고, 지금 단계 것만 빛난다.
 * 답변 단계는 최종 SQL이 실제로 쓴 경로(테이블, 조인, 대응 클래스·관계)만 보여준다.
 */
export function computeTrace(frames: Frame[], cursor: number, idx: OntologyIndex | null): TraceHighlight | null {
  const cur = frames[cursor]
  if (!cur) return null
  const h: TraceHighlight = {
    tables: new Set(), columns: new Set(), classes: new Set(), props: new Set(), focusTable: null, focusClass: null, active: true,
    now: emptySets(), propOrder: new Map(), joins: [], joinsNow: false,
  }
  const from = cur.kind === 'answer' ? cursor : 0
  for (let i = from; i <= cursor; i++) {
    const it = frameItems(frames[i], idx)
    it.classes.forEach((x) => h.classes.add(x))
    it.props.forEach((x) => h.props.add(x))
    it.tables.forEach((x) => h.tables.add(x))
    it.columns.forEach((x) => h.columns.add(x))
    if (it.joins.length) h.joins = it.joins // 에이전트가 SQL을 고쳐 다시 실행했으면 마지막 것만
    if (i === cursor) {
      it.classes.forEach((x) => h.now.classes.add(x))
      it.props.forEach((x) => h.now.props.add(x))
      it.tables.forEach((x) => h.now.tables.add(x))
      it.columns.forEach((x) => h.now.columns.add(x))
      it.order.forEach((iri) => !h.propOrder.has(iri) && h.propOrder.set(iri, h.propOrder.size))
      h.joinsNow = it.joins.length > 0
    }
  }
  return h
}

export function useFrames(): Frame[] {
  const events = useStore((s) => s.chat?.events)
  return useMemo(() => buildFrames(events ?? []), [events])
}

/** 지금 보여줄 단계 번호: 따라가기 중이면 마지막 단계 */
export function useCursor(): number | null {
  const frames = useFrames()
  const cursor = useStore((s) => s.trace.cursor)
  if (!frames.length) return null
  return cursor === null ? frames.length - 1 : Math.min(cursor, frames.length - 1)
}

/** 캔버스가 쓰는 강조: 사용자가 무언가를 골랐으면 그 선택, 아니면 질의 경로 */
export function useCanvasHighlight(): Highlight & Partial<TraceHighlight> {
  const selected = useHighlight()
  const frames = useFrames()
  const cursor = useCursor()
  const show = useStore((s) => s.trace.show)
  const idx = useOntologyIndex()
  const trace = useMemo(() => (show && cursor !== null ? computeTrace(frames, cursor, idx) : null), [show, frames, cursor, idx])
  return selected.active || !trace ? selected : trace
}
