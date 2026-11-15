import { useEffect } from 'react'
import { useStore } from '../store'
import { useCursor, useFrames } from '../trace'

const STEP_MS = 1800

function Btn({ label, title, onClick, disabled, active }: { label: string; title: string; onClick: () => void; disabled?: boolean; active?: boolean }) {
  return (
    <button
      type="button"
      title={title}
      aria-label={title}
      onClick={onClick}
      disabled={disabled}
      className={`h-6 min-w-6 rounded px-1.5 text-[11.5px] leading-none disabled:cursor-not-allowed disabled:opacity-35 ${active ? 'bg-amber-500 text-white' : 'border border-line bg-white hover:bg-slate-50'}`}
    >
      {label}
    </button>
  )
}

/** 경로 재생 막대: 처음/이전/재생/다음/마지막, 최신 따라가기, 화면 자동 맞춤, 경로 표시 */
export function TracePlayer() {
  const frames = useFrames()
  const cursor = useCursor()
  const trace = useStore((s) => s.trace)
  const running = useStore((s) => s.chat?.running ?? false)
  const setTrace = useStore((s) => s.setTrace)
  const last = frames.length - 1

  // 재생: 일정 간격으로 다음 단계로. 끝에 닿으면 멈춘다
  useEffect(() => {
    if (!trace.playing) return
    const t = window.setInterval(() => {
      const { trace: cur, setTrace } = useStore.getState()
      const at = cur.cursor ?? last
      if (at >= last) setTrace({ playing: false })
      else setTrace({ cursor: at + 1 })
    }, STEP_MS)
    return () => window.clearInterval(t)
  }, [trace.playing, last])

  if (cursor === null) return null
  const go = (i: number) => setTrace({ cursor: Math.max(0, Math.min(last, i)), playing: false, show: true })
  const play = () => {
    if (trace.playing) return setTrace({ playing: false })
    // 끝에서 누르면 처음부터
    setTrace({ playing: true, show: true, camera: true, cursor: cursor >= last ? 0 : cursor })
  }
  const following = trace.cursor === null

  return (
    <div className="flex flex-wrap items-center gap-1">
      <Btn label="⏮" title="처음 단계" onClick={() => go(0)} disabled={cursor === 0} />
      <Btn label="◀" title="이전 단계" onClick={() => go(cursor - 1)} disabled={cursor === 0} />
      <Btn label={trace.playing ? '⏸' : '▶'} title={trace.playing ? '일시정지' : '처음부터 단계별로 재생'} onClick={play} disabled={frames.length < 2} active={trace.playing} />
      <Btn label="▶|" title="다음 단계" onClick={() => go(cursor + 1)} disabled={cursor >= last} />
      <Btn label="⏭" title="마지막 단계" onClick={() => go(last)} disabled={cursor >= last} />
      <span className="mx-1 font-mono text-[11px] tabular-nums text-muted">
        {cursor + 1}/{frames.length}
      </span>
      {running && !following && <Btn label="최신 따라가기" title="실행 중인 최신 단계를 계속 보여줍니다" onClick={() => setTrace({ cursor: null, playing: false, show: true })} />}
      <label className="ml-1 flex items-center gap-1 text-[11px] text-slate-600" title="강조된 노드가 화면에 들어오도록 자동으로 맞춥니다. 화면을 직접 움직이면 꺼집니다.">
        <input type="checkbox" checked={trace.camera} onChange={(e) => setTrace({ camera: e.target.checked })} />
        자동 맞춤
      </label>
      <label className="flex items-center gap-1 text-[11px] text-slate-600" title="캔버스에 질의 경로를 표시합니다">
        <input type="checkbox" checked={trace.show} onChange={(e) => setTrace({ show: e.target.checked })} />
        경로 표시
      </label>
    </div>
  )
}
