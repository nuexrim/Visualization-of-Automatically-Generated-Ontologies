import { useState } from 'react'
import { useStore } from '../store'
import { useCursor, useFrames } from '../trace'

/**
 * 캔버스 위에 지금 단계의 쿼리 원문을 띄운다.
 * 온톨로지 캔버스에는 SPARQL, ERD 캔버스에는 SQL (온톨로지 캔버스가 안 보이면 SPARQL도 ERD 쪽에).
 */
export function TraceQuery({ pane }: { pane: 'erd' | 'onto' }) {
  const frames = useFrames()
  const cursor = useCursor()
  const show = useStore((s) => s.trace.show && s.selection === null)
  const view = useStore((s) => s.view)
  const [open, setOpen] = useState(true)
  const f = cursor === null ? undefined : frames[cursor]
  if (!show || !f || !f.input) return null
  const sparql = f.tool === 'ontology_query'
  const ontoVisible = view === 'onto' || view === 'split'
  if (pane === 'onto' && !sparql) return null
  if (pane === 'erd' && sparql && ontoVisible) return null

  const title = f.kind === 'answer' ? '최종 SQL' : sparql ? `${f.label}단계 · 온톨로지 검색 (SPARQL)` : `${f.label}단계 · SQL 실행`
  const status = f.kind === 'answer' ? null : !f.done ? '실행 중…' : f.result?.rejected ? '거부됨' : f.result?.ok ? null : '결과 없음/오류'
  return (
    <div className={`absolute right-3 top-3 z-10 w-[min(460px,calc(100%-24px))] overflow-hidden rounded-lg border bg-white/95 shadow-lg backdrop-blur ${sparql ? 'border-onto/50' : 'border-amber-500/60'}`}>
      <button type="button" onClick={() => setOpen(!open)} className="flex w-full items-center gap-2 px-2.5 py-1 text-left">
        <span className={`rounded px-1.5 py-0.5 text-[10px] font-bold text-white ${sparql ? 'bg-onto' : 'bg-amber-600'}`}>{sparql ? 'SPARQL' : 'SQL'}</span>
        <span className="min-w-0 flex-1 truncate text-[11.5px] font-medium">{title}</span>
        {status && <span className="shrink-0 text-[11px] text-amber-700">{status}</span>}
        <span className="shrink-0 text-[11px] text-muted">{open ? '접기' : '펼치기'}</span>
      </button>
      {open && <pre className="max-h-44 overflow-auto whitespace-pre-wrap break-words border-t border-slate-100 bg-slate-900 px-2.5 py-2 font-mono text-[10.5px] leading-snug text-slate-100">{f.input}</pre>}
    </div>
  )
}
