import { useEffect, useState } from 'react'
import { useStore } from '../store'
import type { GenState, GenTable, StepEvent, StepName } from '../types'

const STEP_LABEL: Record<StepName, string> = {
  direct_mapping: '1. Direct Mapping 뼈대',
  context: '2. 맥락 검색',
  generate: '3. 생성 LLM 의미 보강',
  judge: '4. 판정 LLM 검토',
  validate: '파싱 결과 검사 · 병합',
}

function StatusIcon({ status }: { status: 'pending' | 'running' | 'done' | 'failed' | 'enriched' | 'direct_only' }) {
  if (status === 'running') return <span className="spinner text-accent" aria-label="진행 중" />
  const map = {
    pending: ['○', 'text-slate-300', '대기'],
    done: ['✓', 'text-onto', '완료'],
    enriched: ['✓', 'text-onto', '보강 완료'],
    direct_only: ['◐', 'text-amber-600', 'Direct Mapping만 유지'],
    failed: ['✕', 'text-red-600', '실패'],
  } as const
  const [glyph, color, label] = map[status]
  return (
    <span className={`inline-block w-3 text-center text-[12px] font-bold leading-none ${color}`} aria-label={label}>
      {glyph}
    </span>
  )
}

function Step({ e }: { e: StepEvent }) {
  const [open, setOpen] = useState(false)
  const issues = e.issues ? [...e.issues.critical.map((x) => `치명적: ${x}`), ...e.issues.important.map((x) => `중요: ${x}`), ...e.issues.minor.map((x) => `사소: ${x}`)] : []
  const notes = [...(e.errors ?? []).map((x) => `오류: ${x}`), ...(e.warnings ?? []).map((x) => `경고: ${x}`), ...issues]
  const expandable = Boolean(e.text) || notes.length > 0
  return (
    <li>
      <button className={`flex w-full items-start gap-2 rounded px-1 py-0.5 text-left ${expandable ? 'hover:bg-slate-100' : 'cursor-default'}`} onClick={() => expandable && setOpen(!open)} aria-expanded={expandable ? open : undefined}>
        <span className="mt-[3px]">
          <StatusIcon status={e.status} />
        </span>
        <span className="min-w-0 flex-1">
          <span className="text-[12px]">
            {STEP_LABEL[e.step]}
            {e.attempt && e.attempt > 1 ? ` (재시도 ${e.attempt - 1})` : ''}
          </span>
          {e.detail && <span className="ml-1.5 text-[11px] text-muted">{e.detail}</span>}
        </span>
        {expandable && <span className="text-[10px] text-muted">{open ? '접기' : '보기'}</span>}
      </button>
      {open && (
        <div className="ml-5 mt-1 space-y-1">
          {notes.map((n, i) => (
            <p key={i} className={`text-[11px] leading-snug ${n.startsWith('오류') || n.startsWith('치명적') ? 'text-red-700' : 'text-slate-600'}`}>
              {n}
            </p>
          ))}
          {e.text && <pre className="max-h-64 overflow-auto whitespace-pre-wrap break-words rounded bg-slate-900 p-2 font-mono text-[10.5px] leading-snug text-slate-100">{e.text}</pre>}
        </div>
      )}
    </li>
  )
}

function TableRow({ t, current, llmChars }: { t: GenTable; current: boolean; llmChars: number }) {
  const select = useStore((s) => s.select)
  const [open, setOpen] = useState(false)
  const expanded = current || open
  const running = t.steps.find((s) => s.status === 'running')
  return (
    <li className={`rounded-lg border ${current ? 'border-accent bg-blue-50/50' : 'border-transparent'}`}>
      <button
        className="flex w-full items-center gap-2 px-2 py-1.5 text-left hover:bg-slate-50 disabled:hover:bg-transparent"
        disabled={t.status === 'pending'}
        aria-expanded={expanded}
        onClick={() => {
          setOpen(!open)
          select({ kind: 'table', table: t.name })
        }}
      >
        <StatusIcon status={t.status === 'done' ? (t.outcome ?? 'done') : t.status} />
        <span className={`font-mono text-[12px] ${t.status === 'pending' ? 'text-slate-400' : ''}`}>{t.name}</span>
        <span className="ml-auto text-[11px] text-muted">
          {t.status === 'done' ? (t.outcome === 'enriched' ? '보강됨' : 'Direct Mapping만') : running ? STEP_LABEL[running.step].replace(/^\d\. /, '') : ''}
        </span>
      </button>
      {expanded && t.steps.length > 0 && (
        <ul className="space-y-0.5 px-2 pb-2">
          {t.steps.map((s) => (
            <Step key={`${s.step}-${s.attempt ?? 0}`} e={s} />
          ))}
          {current && running && (running.step === 'generate' || running.step === 'judge') && llmChars > 0 && (
            <li className="ml-5 text-[11px] text-muted">응답 수신 중… {llmChars.toLocaleString()}자</li>
          )}
        </ul>
      )}
    </li>
  )
}

function Elapsed({ gen }: { gen: GenState }) {
  const [now, setNow] = useState(Date.now())
  useEffect(() => {
    if (!gen.running) return
    const id = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(id)
  }, [gen.running])
  const sec = Math.round(((gen.finishedAt ?? now) - gen.startedAt) / 1000)
  return (
    <span>
      {Math.floor(sec / 60)}분 {sec % 60}초
    </span>
  )
}

/** 온톨로지 자동 생성 진행 상황. 테이블을 외래 키 의존 순서로 하나씩 처리하는 과정을 보여준다. */
export function GenerationPanel({ gen }: { gen: GenState }) {
  const stop = useStore((s) => s.stopGenerate)
  const close = useStore((s) => s.closeGen)
  const loadFile = useStore((s) => s.loadFile)
  const done = gen.tables.filter((t) => t.status === 'done').length
  const enriched = gen.tables.filter((t) => t.outcome === 'enriched').length
  const total = gen.tables.length

  return (
    <aside className="flex w-[360px] shrink-0 flex-col border-l border-line bg-white">
      <div className="border-b border-line px-4 py-3">
        <div className="flex items-center justify-between gap-2">
          <h2 className="text-[14px] font-semibold">온톨로지 자동 생성</h2>
          {gen.running ? (
            <button className="rounded-md border border-red-300 px-2 py-0.5 text-[12px] text-red-700 hover:bg-red-50" onClick={stop}>
              중지
            </button>
          ) : (
            <button className="rounded px-1.5 text-muted hover:bg-slate-100" onClick={close} aria-label="닫기">
              ✕
            </button>
          )}
        </div>
        <div className="mt-0.5 text-[11px] text-muted">
          {gen.mode === 'rigor' ? `RIGOR 방식 · ${gen.model ?? ''}` : 'Direct Mapping만'} · <Elapsed gen={gen} />
        </div>
        <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-slate-100" role="progressbar" aria-valuemin={0} aria-valuemax={total} aria-valuenow={done}>
          <div className="h-full rounded-full bg-onto transition-[width] duration-300" style={{ width: total ? `${(done / total) * 100}%` : '0%' }} />
        </div>
        <div className="mt-1 text-[11px] text-muted">
          테이블 {done} / {total}
          {gen.mode === 'rigor' && done > 0 ? ` · 보강 ${enriched} · Direct Mapping만 ${done - enriched}` : ''}
        </div>
      </div>

      {gen.error && <div className="border-b border-red-200 bg-red-50 px-4 py-2 text-[12px] text-red-800">{gen.error}</div>}

      {gen.file && (
        <div className="border-b border-line bg-onto-soft px-4 py-3">
          <div className="text-[12px] font-semibold text-onto">파일을 만들었습니다</div>
          <div className="mt-0.5 break-all font-mono text-[11px]">{gen.file.filename}</div>
          <div className="mt-0.5 text-[11px] text-muted">
            클래스 {gen.file.counts.classes} · 데이터 속성 {gen.file.counts.data_properties} · 객체 속성 {gen.file.counts.object_properties}
            {gen.usage && gen.usage.calls > 0 ? ` · LLM 호출 ${gen.usage.calls}회 (입력 ${gen.usage.input_tokens.toLocaleString()} / 출력 ${gen.usage.output_tokens.toLocaleString()} 토큰)` : ''}
          </div>
          <button className="mt-2 rounded-md bg-onto px-3 py-1 text-[12px] font-medium text-white hover:brightness-110" onClick={() => void loadFile(gen.file!.filename)}>
            이 파일 불러오기
          </button>
        </div>
      )}

      <ul className="min-h-0 flex-1 space-y-0.5 overflow-y-auto p-2">
        {gen.tables.map((t) => (
          <TableRow key={t.name} t={t} current={gen.running && gen.current === t.name} llmChars={gen.llmChars} />
        ))}
        {total === 0 && !gen.error && <li className="px-2 py-4 text-center text-[12px] text-muted">스키마를 읽는 중…</li>}
      </ul>
    </aside>
  )
}
