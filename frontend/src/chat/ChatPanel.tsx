import { useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api'
import { useStore } from '../store'
import { useCursor } from '../trace'
import type { AgentPrompt, Question } from '../types'
import { ResultView } from './ResultView'
import { Timeline } from './Timeline'
import { TracePlayer } from './TracePlayer'

const HEIGHT_KEY = 'ontolens:chat-height'
const MIN_HEIGHT = 160
const DIFFICULTY: Record<Question['difficulty'], string> = { easy: 'bg-emerald-100 text-emerald-800', medium: 'bg-sky-100 text-sky-800', hard: 'bg-amber-100 text-amber-800', extra: 'bg-rose-100 text-rose-800' }

function Examples({ onPick, onClose }: { onPick: (q: Question) => void; onClose: () => void }) {
  const questions = useStore((s) => s.questions)
  const [filter, setFilter] = useState('')
  const shown = useMemo(() => {
    const f = filter.trim().toLowerCase()
    return (f ? questions.filter((q) => q.question.toLowerCase().includes(f) || q.difficulty === f) : questions).slice(0, 200)
  }, [questions, filter])
  return (
    <div className="absolute bottom-full left-0 z-30 mb-1 flex max-h-[420px] w-[620px] max-w-[90vw] flex-col overflow-hidden rounded-xl border border-line bg-white shadow-2xl" role="dialog" aria-label="예시 질문">
      <div className="flex items-center gap-2 border-b border-line px-3 py-2">
        <input autoFocus value={filter} onChange={(e) => setFilter(e.target.value)} placeholder={`예시 질문 ${questions.length}개에서 찾기 (BIRD)`} className="h-7 flex-1 rounded-md border border-line px-2 text-[12px]" />
        <button className="rounded px-1.5 text-muted hover:bg-slate-100" onClick={onClose} aria-label="닫기">
          ✕
        </button>
      </div>
      <ul className="min-h-0 flex-1 overflow-y-auto">
        {shown.map((q) => (
          <li key={q.id}>
            <button className="flex w-full items-start gap-2 border-b border-slate-100 px-3 py-1.5 text-left hover:bg-slate-50" onClick={() => onPick(q)}>
              <span className={`mt-0.5 w-[52px] shrink-0 rounded px-1 py-0.5 text-center text-[10px] font-semibold ${DIFFICULTY[q.difficulty]}`}>{q.difficulty}</span>
              <span className="min-w-0 flex-1 text-[12px] leading-snug">
                {q.question}
                {q.evidence && <span className="block truncate text-[11px] text-muted">Hint: {q.evidence}</span>}
              </span>
            </button>
          </li>
        ))}
        {shown.length === 0 && <li className="px-3 py-6 text-center text-[12px] text-muted">맞는 질문이 없습니다</li>}
      </ul>
    </div>
  )
}

/** 저장된 질의 기록 목록. 고르면 실행 기록과 결과가 복원되고 처음 단계부터 재생할 수 있다. */
function History({ onClose }: { onClose: () => void }) {
  const runs = useStore((s) => s.runs)
  const openRun = useStore((s) => s.openRun)
  const current = useStore((s) => s.ontology?.filename)
  const refresh = useStore((s) => s.refreshRuns)
  useEffect(() => {
    void refresh()
  }, [refresh])
  return (
    <div className="absolute bottom-full left-0 z-30 mb-1 flex max-h-[420px] w-[620px] max-w-[90vw] flex-col overflow-hidden rounded-xl border border-line bg-white shadow-2xl" role="dialog" aria-label="질의 기록">
      <div className="flex items-center gap-2 border-b border-line px-3 py-2">
        <span className="flex-1 text-[12px] font-semibold">질의 기록 {runs.length}개</span>
        <button className="rounded px-1.5 text-muted hover:bg-slate-100" onClick={onClose} aria-label="닫기">
          ✕
        </button>
      </div>
      <ul className="min-h-0 flex-1 overflow-y-auto">
        {runs.map((r) => (
          <li key={r.id}>
            <button
              className="flex w-full items-start gap-2 border-b border-slate-100 px-3 py-1.5 text-left hover:bg-slate-50"
              onClick={() => {
                void openRun(r.id)
                onClose()
              }}
            >
              <span className={`mt-0.5 w-[52px] shrink-0 rounded px-1 py-0.5 text-center text-[10px] font-semibold ${r.status === 'answer' ? 'bg-emerald-100 text-emerald-800' : 'bg-rose-100 text-rose-800'}`}>{r.status === 'answer' ? '답변' : '오류'}</span>
              <span className="min-w-0 flex-1 text-[12px] leading-snug">
                {r.question}
                <span className="block truncate font-mono text-[10.5px] text-muted">
                  {r.created_at?.replace('T', ' ').slice(0, 19)} · 도구 {r.steps}회{r.seconds_total != null ? ` · ${r.seconds_total.toFixed(1)}초` : ''} · {r.model}
                  {r.ontology_file && r.ontology_file !== current ? ` · 다른 온톨로지(${r.ontology_file})` : ''}
                </span>
              </span>
            </button>
          </li>
        ))}
        {runs.length === 0 && <li className="px-3 py-6 text-center text-[12px] text-muted">저장된 기록이 없습니다</li>}
      </ul>
    </div>
  )
}

function PromptDialog({ onClose }: { onClose: () => void }) {
  const [data, setData] = useState<AgentPrompt | null>(null)
  useEffect(() => {
    void api.agentPrompt().then(setData)
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])
  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-slate-900/40 p-4" onClick={onClose}>
      <div role="dialog" aria-modal="true" aria-label="에이전트 설정" className="flex max-h-[85vh] w-[760px] max-w-full flex-col rounded-xl bg-white shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between border-b border-line px-5 py-3">
          <h2 className="text-[14px] font-semibold">에이전트 설정 (논문의 sparql 조건)</h2>
          <button className="rounded px-2 py-1 text-muted hover:bg-slate-100" onClick={onClose} aria-label="닫기">
            ✕
          </button>
        </div>
        <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-5 py-4 text-[12px]">
          {!data ? (
            <p className="text-muted">불러오는 중…</p>
          ) : (
            <>
              <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1">
                <dt className="text-muted">모델</dt>
                <dd className="font-mono">{data.model ?? '(AGENT_MODEL 미설정)'}</dd>
                <dt className="text-muted">도구</dt>
                <dd className="font-mono">{data.tools.join(', ')}</dd>
                <dt className="text-muted">제한</dt>
                <dd>
                  질문당 최대 {data.limits.max_steps}단계 · 도구 결과 최대 {data.limits.max_rows}행 · SQL 시간 제한 {data.limits.sql_timeout_sec}초
                </dd>
                <dt className="text-muted">실행 조건</dt>
                <dd>온톨로지 검색이 결과를 돌려주기 전에는 SQL 실행을 코드로 거부합니다.</dd>
              </dl>
              <div>
                <h3 className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-muted">시스템 프롬프트</h3>
                <pre className="whitespace-pre-wrap rounded-lg bg-slate-900 p-3 font-mono text-[11px] leading-relaxed text-slate-100">{data.system_prompt}</pre>
              </div>
              <div>
                <h3 className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-muted">SQL 거부 시 돌려주는 메시지</h3>
                <pre className="whitespace-pre-wrap rounded-lg bg-slate-100 p-3 font-mono text-[11px] leading-relaxed">{data.gate_message}</pre>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}

/** 하단 채팅창: 질문 입력, 단계별 실행 기록, 최종 SQL, 결과 표. 위쪽 경계를 끌어 높이를 조절한다. */
export function ChatPanel() {
  const ontology = useStore((s) => s.ontology)
  const chat = useStore((s) => s.chat)
  const hasExamples = useStore((s) => s.questions.length > 0)
  const generating = useStore((s) => s.gen?.running ?? false)
  const ask = useStore((s) => s.ask)
  const stop = useStore((s) => s.stopChat)

  const [question, setQuestion] = useState('')
  const [evidence, setEvidence] = useState('')
  const [useEvidence, setUseEvidence] = useState(true)
  const [examples, setExamples] = useState(false)
  const [prompt, setPrompt] = useState(false)
  const [history, setHistory] = useState(false)
  const hasRuns = useStore((s) => s.runs.length > 0)
  const following = useStore((s) => s.trace.cursor === null)
  const cursor = useCursor()
  const ontologyFile = useStore((s) => s.ontology?.filename)
  const [height, setHeight] = useState(() => Number(localStorage.getItem(HEIGHT_KEY)) || 340)
  const timeline = useRef<HTMLDivElement>(null)

  // 최신 단계를 따라가는 중이면 새 단계가 올 때 실행 기록을 맨 아래로, 아니면 고른 단계가 보이게
  const count = chat?.events.length ?? 0
  useEffect(() => {
    if (following) timeline.current?.scrollTo({ top: timeline.current.scrollHeight, behavior: 'smooth' })
  }, [count, following])
  useEffect(() => {
    if (!following && cursor !== null) timeline.current?.querySelector(`[data-frame="${cursor}"]`)?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  }, [cursor, following])
  const start = chat?.events.find((e) => e.type === 'start')
  const recordedWith = start?.type === 'start' ? start.ontology_file : null

  const startResize = (e: React.PointerEvent) => {
    e.preventDefault()
    const startY = e.clientY
    const startH = height
    const move = (ev: PointerEvent) => setHeight(Math.max(MIN_HEIGHT, Math.min(window.innerHeight - 140, startH + startY - ev.clientY)))
    const up = () => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', up)
      setHeight((h) => (localStorage.setItem(HEIGHT_KEY, String(h)), h))
    }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', up)
  }

  const ready = ontology !== null && !generating
  const running = chat?.running ?? false
  const submit = () => {
    if (ready && !running && question.trim()) void ask(question, evidence, useEvidence)
  }

  return (
    <footer className="relative flex shrink-0 flex-col border-t border-line bg-white" style={{ height: chat ? height : undefined }}>
      {chat && <div className="absolute inset-x-0 -top-1 z-10 h-2 cursor-row-resize hover:bg-accent/20" onPointerDown={startResize} role="separator" aria-orientation="horizontal" aria-label="채팅창 높이 조절" />}

      {chat && (
        <div className="flex min-h-0 flex-1 divide-x divide-line">
          <div ref={timeline} className="min-w-0 flex-1 overflow-y-auto bg-canvas p-3">
            <div className="sticky -top-3 z-10 -mx-3 -mt-3 mb-2 flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-line bg-canvas/95 px-3 py-1.5 backdrop-blur">
              <h3 className="text-[11px] font-semibold uppercase tracking-wide text-muted">실행 기록{chat.runId ? ' (저장된 기록)' : ''}</h3>
              <TracePlayer />
            </div>
            {chat.runId && recordedWith && recordedWith !== ontologyFile && (
              <p className="mb-2 rounded-md bg-amber-50 px-2.5 py-1.5 text-[11.5px] leading-snug text-amber-800">
                이 기록은 다른 온톨로지 파일(<span className="font-mono">{recordedWith}</span>)로 실행했습니다. 지금 불러온 파일에 없는 클래스·속성은 캔버스에 강조되지 않습니다.
              </p>
            )}
            <Timeline events={chat.events} running={running} cursor={cursor} />
          </div>
          <div className="min-w-0 flex-1 overflow-y-auto p-3">
            <ResultView events={chat.events} running={running} />
          </div>
        </div>
      )}

      <div className={`relative flex flex-col gap-1.5 px-3 py-2 ${chat ? 'border-t border-line' : ''}`}>
        {history && <History onClose={() => setHistory(false)} />}
        {examples && (
          <Examples
            onClose={() => setExamples(false)}
            onPick={(q) => {
              setQuestion(q.question)
              setEvidence(q.evidence)
              setExamples(false)
            }}
          />
        )}
        <div className="flex items-center gap-2">
          <span className="text-[12px] font-semibold">채팅</span>
          <button className="shrink-0 whitespace-nowrap rounded-md border border-line px-2 py-1 text-[12px] hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-45" disabled={!ready || !hasExamples} title={hasExamples ? undefined : '이 DB에는 BIRD 예시 질문이 없습니다'} onClick={() => (setExamples(!examples), setHistory(false))}>
            예시 질문 ▴
          </button>
          <button className="shrink-0 whitespace-nowrap rounded-md border border-line px-2 py-1 text-[12px] hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-45" disabled={running || !hasRuns} title={hasRuns ? '저장된 질의를 다시 열어 재생합니다' : '저장된 기록이 없습니다'} onClick={() => (setHistory(!history), setExamples(false))}>
            기록 ▴
          </button>
          <input
            value={question}
            disabled={!ready || running}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && !e.nativeEvent.isComposing && submit()}
            placeholder={ready ? 'DB에 대해 질문하세요 (Enter로 실행)' : generating ? '온톨로지를 생성하는 중에는 질문할 수 없습니다' : '온톨로지 파일을 불러온 뒤 질문할 수 있습니다'}
            aria-label="질문"
            className="h-8 min-w-0 flex-1 rounded-md border border-line px-2.5 text-[12.5px] disabled:cursor-not-allowed disabled:bg-slate-50"
          />
          {running ? (
            <button className="shrink-0 rounded-md border border-red-300 px-3 py-1 text-[12px] text-red-700 hover:bg-red-50" onClick={stop}>
              중지
            </button>
          ) : (
            <button className="shrink-0 rounded-md bg-accent px-3 py-1 text-[12px] font-medium text-white hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-45" disabled={!ready || !question.trim()} onClick={submit}>
              실행
            </button>
          )}
          <button className="shrink-0 whitespace-nowrap rounded-md border border-line px-2 py-1 text-[12px] hover:bg-slate-50" onClick={() => setPrompt(true)} title="시스템 프롬프트와 실행 조건 보기">
            프롬프트
          </button>
        </div>
        {ready && (
          <div className="flex items-center gap-2 pl-[38px]">
            <label className="flex shrink-0 items-center gap-1.5 text-[11.5px] text-slate-600">
              <input type="checkbox" checked={useEvidence} onChange={(e) => setUseEvidence(e.target.checked)} disabled={running} />
              evidence 힌트 붙이기
            </label>
            <input
              value={evidence}
              disabled={!useEvidence || running}
              onChange={(e) => setEvidence(e.target.value)}
              placeholder="힌트 (예시 질문을 고르면 BIRD evidence가 채워집니다)"
              aria-label="evidence 힌트"
              className="h-6 min-w-0 flex-1 rounded border border-line px-2 text-[11.5px] disabled:bg-slate-50 disabled:text-slate-400"
            />
          </div>
        )}
      </div>
      {prompt && <PromptDialog onClose={() => setPrompt(false)} />}
    </footer>
  )
}
