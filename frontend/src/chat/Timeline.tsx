import { useState } from 'react'
import { useStore } from '../store'
import type { ChatEvent, ResultTable, ToolName } from '../types'

const TOOL: Record<ToolName, { label: string; badge: string; tone: string; border: string }> = {
  ontology_query: { label: '온톨로지 검색', badge: 'SPARQL', tone: 'bg-onto text-white', border: 'border-onto/40' },
  sql_query: { label: 'SQL 실행', badge: 'SQL', tone: 'bg-accent text-white', border: 'border-accent/40' },
}

const sec = (s: number) => `${s < 10 ? s.toFixed(1) : Math.round(s)}초`

function Output({ text, table }: { text: string; table: ResultTable | null }) {
  const [open, setOpen] = useState(false)
  const lines = text.split('\n')
  const long = lines.length > 6 || text.length > 500
  const shown = open || !long ? text : lines.slice(0, 6).join('\n').slice(0, 500)
  return (
    <div>
      <pre className="overflow-x-auto whitespace-pre rounded bg-slate-50 p-2 font-mono text-[10.5px] leading-snug text-slate-700">{shown}</pre>
      {long && (
        <button className="mt-0.5 text-[11px] text-accent hover:underline" onClick={() => setOpen(!open)}>
          {open ? '접기' : `전체 보기 (${table ? `${table.rows.length}행${table.truncated ? ', 50행에서 잘림' : ''}` : `${lines.length}줄`})`}
        </button>
      )}
    </div>
  )
}

type Call = Extract<ChatEvent, { type: 'tool_call' }>
type Result = Extract<ChatEvent, { type: 'tool_result' }>

/** 단계 머리줄: 누르면 캔버스가 그 시점의 강조 상태로 돌아간다 */
function frameProps(frame: number, cursor: number | null) {
  const current = frame === cursor
  const future = cursor !== null && frame > cursor
  return { current, future }
}

function ToolStep({ call, result, frame, cursor, onPick }: { call: Call; result: Result | undefined; frame: number; cursor: number | null; onPick: (i: number) => void }) {
  const t = TOOL[call.tool]
  const { current, future } = frameProps(frame, cursor)
  const status = !result ? null : result.rejected ? '거부됨' : result.ok ? '성공' : call.tool === 'ontology_query' && result.output === '(no results)' ? '결과 없음' : '오류'
  const bad = result && !result.ok
  return (
    <li data-frame={frame} className={`rounded-lg border bg-white transition-opacity ${result?.rejected ? 'border-red-300' : t.border} ${current ? 'ring-2 ring-amber-500/70' : ''} ${future ? 'opacity-45' : ''}`}>
      <button type="button" onClick={() => onPick(frame)} title="이 단계의 강조 상태를 캔버스에 보기" className="flex w-full items-center gap-2 rounded-t-lg px-2.5 py-1.5 text-left hover:bg-slate-50">
        <span className="w-5 text-center font-mono text-[11px] text-muted">{call.step}</span>
        <span className={`rounded px-1.5 py-0.5 text-[10px] font-bold tracking-wide ${t.tone}`}>{t.badge}</span>
        <span className="text-[12px] font-medium">{t.label}</span>
        <span className="ml-auto flex items-center gap-2 text-[11px] text-muted">
          {result ? (
            <>
              <span className={bad ? (result.rejected ? 'font-semibold text-red-700' : 'text-amber-700') : 'text-onto'}>{status}</span>
              <span title="모델이 이 호출을 정하는 데 걸린 시간 + 도구 실행 시간">{sec(call.seconds + result.seconds)}</span>
            </>
          ) : (
            <span className="spinner text-accent" aria-label="실행 중" />
          )}
          {current && <span className="rounded bg-amber-500 px-1 text-[10px] font-bold text-white">캔버스</span>}
        </span>
      </button>
      <div className="space-y-1.5 border-t border-slate-100 px-2.5 py-2">
        <div>
          <div className="mb-0.5 text-[10px] font-semibold uppercase tracking-wide text-muted">입력</div>
          <pre className="overflow-x-auto whitespace-pre-wrap break-words rounded bg-slate-900 p-2 font-mono text-[10.5px] leading-snug text-slate-100">{call.input}</pre>
        </div>
        {result && (
          <div>
            <div className="mb-0.5 text-[10px] font-semibold uppercase tracking-wide text-muted">결과</div>
            {result.rejected ? (
              <p className="rounded bg-red-50 p-2 text-[11.5px] leading-snug text-red-800">
                온톨로지를 검색하기 전이라 SQL 실행이 거부되었습니다.
                <span className="mt-1 block font-mono text-[10.5px] text-red-700">{result.output}</span>
              </p>
            ) : (
              <Output text={result.output} table={result.table} />
            )}
          </div>
        )}
      </div>
    </li>
  )
}

/** 실행 기록: 생각 → 도구 호출(입력) → 결과 순서로 보여준다. */
export function Timeline({ events, running, cursor }: { events: ChatEvent[]; running: boolean; cursor: number | null }) {
  const setTrace = useStore((s) => s.setTrace)
  const onPick = (i: number) => setTrace({ cursor: i, playing: false, show: true })
  // 이벤트 → 단계 번호 (tool_call, answer 순서대로)
  const frameOf = new Map<ChatEvent, number>()
  let n = 0
  for (const e of events) if (e.type === 'tool_call' || e.type === 'answer') frameOf.set(e, n++)
  const results = new Map(events.filter((e): e is Result => e.type === 'tool_result').map((e) => [e.id, e]))
  const start = events.find((e) => e.type === 'start')
  const last = events[events.length - 1]
  const thinking = running && (!last || last.type === 'start' || last.type === 'tool_result')
  return (
    <ol className="space-y-2">
      {start?.type === 'start' && (
        <li className="rounded-lg bg-slate-100 px-2.5 py-1.5 text-[11.5px] leading-snug text-slate-600">
          <span className="font-medium text-ink">{start.question}</span>
          {start.use_evidence && <span className="mt-0.5 block text-[11px]">Hint: {start.evidence}</span>}
          <span className="mt-0.5 block font-mono text-[10px] text-muted">
            {start.model} · {start.ontology_file}
          </span>
        </li>
      )}
      {events.map((e, i) => {
        if (e.type === 'thought') {
          return (
            <li key={i} className="flex gap-2 px-1 text-[12px] leading-relaxed text-slate-600">
              <span className="mt-0.5 shrink-0 rounded bg-slate-200 px-1.5 py-0.5 text-[10px] font-bold text-slate-600">생각</span>
              <span className="whitespace-pre-wrap">{e.text}</span>
            </li>
          )
        }
        if (e.type === 'tool_call') return <ToolStep key={i} call={e} result={results.get(e.id)} frame={frameOf.get(e)!} cursor={cursor} onPick={onPick} />
        if (e.type === 'answer') {
          const frame = frameOf.get(e)!
          const { current } = frameProps(frame, cursor)
          return (
            <li key={i} data-frame={frame}>
              <button type="button" onClick={() => onPick(frame)} title="사용한 클래스·관계·테이블 전체를 캔버스에 보기" className={`flex w-full gap-2 rounded-lg px-1 py-1 text-left text-[12px] text-slate-600 hover:bg-white ${current ? 'bg-white ring-2 ring-amber-500/70' : ''}`}>
              <span className="mt-0.5 shrink-0 rounded bg-slate-800 px-1.5 py-0.5 text-[10px] font-bold text-white">답변</span>
              <span>
                도구 호출 {e.steps}회 · {sec(e.seconds_total)} · 토큰 입력 {e.tokens_total.input.toLocaleString()} / 출력 {e.tokens_total.output.toLocaleString()}
              </span>
              </button>
            </li>
          )
        }
        if (e.type === 'error') {
          return (
            <li key={i} className="rounded-lg border border-red-300 bg-red-50 px-2.5 py-1.5 text-[12px] text-red-800">
              {e.message}
            </li>
          )
        }
        return null
      })}
      {thinking && (
        <li className="flex items-center gap-2 px-1 text-[12px] text-muted">
          <span className="spinner text-accent" /> 모델이 다음 단계를 생각하는 중…
        </li>
      )}
    </ol>
  )
}
