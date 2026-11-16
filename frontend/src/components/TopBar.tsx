import { useEffect, useRef, useState } from 'react'
import { useStore } from '../store'
import type { ViewMode } from '../types'

/** 불러올 수 있는 DB 파일 확장자 */
export const DB_FILE_ACCEPT = '.dump,.backup,.pgdump,.sql,.sqlite,.sqlite3,.db'

const VIEWS: { id: ViewMode; label: string; title: string }[] = [
  { id: 'erd', label: 'ERD', title: 'DB 구조만 봅니다 (온톨로지 정보 없음)' },
  { id: 'erd-onto', label: 'ERD + 온톨로지', title: '온톨로지로 더 알게 된 정보(클래스, 속성 라벨·설명, 관계)를 ERD 위에 함께 봅니다' },
  { id: 'onto', label: '온톨로지', title: '온톨로지 그래프' },
  { id: 'split', label: '나란히', title: '왼쪽 ERD, 오른쪽 온톨로지' },
]

function Stat({ label, value, title }: { label: string; value: number; title: string }) {
  return (
    <span title={title} className="inline-flex items-baseline gap-1 rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[11px]">
      <span className="text-muted">{label}</span>
      <span className="font-semibold">{value}</span>
    </span>
  )
}

function GenerateButton({ disabled, generating, onPick }: { disabled: boolean; generating: boolean; onPick: (mode: 'rigor' | 'direct') => void }) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const close = (e: MouseEvent | KeyboardEvent) => {
      if (e instanceof KeyboardEvent ? e.key === 'Escape' : !ref.current?.contains(e.target as Node)) setOpen(false)
    }
    window.addEventListener('mousedown', close)
    window.addEventListener('keydown', close)
    return () => {
      window.removeEventListener('mousedown', close)
      window.removeEventListener('keydown', close)
    }
  }, [open])
  const item = 'block w-full px-3 py-2 text-left hover:bg-slate-50'
  return (
    <div ref={ref} className="relative">
      <button
        className="shrink-0 whitespace-nowrap rounded-md border border-accent bg-accent px-2.5 py-1 text-[12px] font-medium text-white hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-45"
        disabled={disabled}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
      >
        {generating ? '생성 중…' : '온톨로지 생성하기 ▾'}
      </button>
      {open && (
        <div role="menu" className="fixed right-3 top-11 z-30 w-[300px] overflow-hidden rounded-lg border border-line bg-white shadow-xl">
          <button role="menuitem" className={item} onClick={() => (setOpen(false), onPick('rigor'))}>
            <div className="text-[12px] font-semibold">RIGOR 방식 (LLM 보강 · 판정)</div>
            <div className="text-[11px] text-muted">테이블마다 Direct Mapping → 맥락 검색 → 생성 LLM → 판정 LLM. 몇 분 걸리고 API 비용이 듭니다.</div>
          </button>
          <button role="menuitem" className={`${item} border-t border-line`} onClick={() => (setOpen(false), onPick('direct'))}>
            <div className="text-[12px] font-semibold">Direct Mapping만</div>
            <div className="text-[11px] text-muted">LLM 없이 뼈대만 만듭니다. 바로 끝납니다.</div>
          </button>
        </div>
      )}
    </div>
  )
}

const btn = 'shrink-0 whitespace-nowrap rounded-md border border-line bg-white px-2.5 py-1 text-[12px] hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-45 disabled:hover:bg-white'

export function TopBar() {
  const dbs = useStore((s) => s.dbs)
  const db = useStore((s) => s.db)
  const schema = useStore((s) => s.schema)
  const ontology = useStore((s) => s.ontology)
  const files = useStore((s) => s.files)
  const view = useStore((s) => s.view)
  const gen = useStore((s) => s.gen)
  const generating = gen?.running ?? false
  const selectDb = useStore((s) => s.selectDb)
  const setView = useStore((s) => s.setView)
  const fit = useStore((s) => s.fit)
  const edgeLabels = useStore((s) => s.edgeLabels)
  const setEdgeLabels = useStore((s) => s.setEdgeLabels)
  const relayout = useStore((s) => s.relayout)
  const generate = useStore((s) => s.generate)
  const setFilesOpen = useStore((s) => s.setFilesOpen)
  const importing = useStore((s) => s.importing)
  const importDb = useStore((s) => s.importDb)
  const closeDb = useStore((s) => s.closeDb)
  const dbInput = useRef<HTMLInputElement>(null)
  const stats = schema?.stats
  const history = ontology?.history
  const editing = useStore((s) => s.editing)
  const undo = useStore((s) => s.undo)
  const redo = useStore((s) => s.redo)
  const saveVersion = useStore((s) => s.saveVersion)
  const setDiffOpen = useStore((s) => s.setDiffOpen)
  const unsaved = history?.changes ?? 0

  return (
    <header className="flex h-12 shrink-0 items-center gap-3 overflow-x-auto border-b border-line bg-white px-3 [&>*]:shrink-0">
      <span className="text-[15px] font-bold tracking-tight">OntoLens</span>
      <input
        ref={dbInput}
        type="file"
        accept={DB_FILE_ACCEPT}
        className="hidden"
        onChange={(e) => {
          const file = e.target.files?.[0]
          if (file) void importDb(file)
          e.target.value = ''
        }}
      />
      <button className={`${btn} font-medium`} disabled={importing !== null || generating} onClick={() => dbInput.current?.click()} title="DB 파일(.dump / .sql / .sqlite)을 읽어 ERD를 만듭니다">
        {importing ? '불러오는 중…' : 'DB 불러오기'}
      </button>
      {dbs.length > 0 && (
        <>
          <select aria-label="불러온 DB 선택" className="rounded-md border border-line bg-white px-2 py-1 font-mono text-[12px]" value={db ?? ''} disabled={generating} onChange={(e) => void selectDb(e.target.value)}>
            {dbs.map((d) => (
              <option key={d.name} value={d.name}>
                {d.name}
              </option>
            ))}
          </select>
          <button className="rounded px-1 text-muted hover:bg-slate-100 disabled:opacity-40" disabled={!db || generating} onClick={() => void closeDb()} title="이 DB 닫기" aria-label="이 DB 닫기">
            ✕
          </button>
        </>
      )}
      {stats && (
        <div className="flex gap-1">
          <Stat label="V" value={stats.V} title="테이블 수" />
          <Stat label="E" value={stats.E} title="외래 키로 이어진 테이블 쌍의 수" />
          <Stat label="C" value={stats.C} title="연결 묶음 수" />
          <Stat label="μ" value={stats.mu} title="순환 수 (E − V + C)" />
        </div>
      )}
      <div className="ml-2 flex overflow-hidden rounded-md border border-line" role="group" aria-label="보기">
        {VIEWS.map((v) => {
          const disabled = generating || (v.id !== 'erd' && !ontology && !gen)
          return (
            <button
              key={v.id}
              disabled={disabled}
              aria-pressed={view === v.id}
              title={generating ? '생성 중에는 나란히 보기로 고정됩니다' : disabled ? '온톨로지 파일을 불러오면 사용할 수 있습니다' : v.title}
              onClick={() => setView(v.id)}
              className={`whitespace-nowrap border-l border-line px-2.5 py-1 text-[12px] first:border-l-0 disabled:cursor-not-allowed disabled:text-slate-400 ${
                view === v.id ? 'bg-slate-800 text-white' : 'bg-white hover:bg-slate-50 disabled:hover:bg-white'
              }`}
            >
              {v.label}
            </button>
          )
        })}
      </div>
      {ontology && (
        <span className="hidden max-w-[220px] truncate rounded bg-onto-soft min-[1800px]:inline px-2 py-0.5 font-mono text-[11px] text-onto" title={`불러온 온톨로지: ${ontology.filename}`}>
          ◆ {ontology.filename}
        </span>
      )}
      {ontology && !gen && (
        <div className="flex items-center gap-1" role="group" aria-label="온톨로지 수정">
          <button className={btn} disabled={!history?.can_undo || editing} onClick={() => void undo()} title={history?.undo_label ? `되돌리기: ${history.undo_label} (⌘Z)` : '되돌릴 수정이 없습니다'}>
            ↶ 되돌리기
          </button>
          <button className={btn} disabled={!history?.can_redo || editing} onClick={() => void redo()} title={history?.redo_label ? `다시하기: ${history.redo_label} (⇧⌘Z)` : '다시 할 수정이 없습니다'}>
            ↷ 다시하기
          </button>
          <button
            className={`${btn} ${unsaved ? 'border-onto font-medium text-onto' : ''}`}
            disabled={!unsaved || editing}
            title={unsaved ? '수정한 작업본을 새 버전 파일로 저장합니다 (원래 파일은 그대로 남습니다)' : '저장할 수정이 없습니다'}
            onClick={() => {
              const note = window.prompt('이 버전에 남길 메모 (선택)', '')
              if (note !== null) void saveVersion(note)
            }}
          >
            저장{unsaved ? ` (${unsaved})` : ''}
          </button>
          <button className={btn} onClick={() => setDiffOpen(true)} title="자동 생성 원본과 비교합니다">
            변경 내용
          </button>
        </div>
      )}
      <div className="ml-auto flex items-center gap-1.5 pl-2">
        <button
          className={`${btn} ${edgeLabels ? 'border-slate-700 bg-slate-800 text-white hover:bg-slate-700' : ''}`}
          aria-pressed={edgeLabels}
          onClick={() => setEdgeLabels(!edgeLabels)}
          title={edgeLabels ? '모든 선의 이름을 보여주는 중입니다. 누르면 고르거나 마우스를 올린 선만 이름을 보여줍니다.' : '고르거나 마우스를 올린 선만 이름을 보여줍니다. 누르면 모든 선의 이름을 보여줍니다.'}
        >
          선 이름
        </button>
        <button className={btn} onClick={fit}>
          화면에 맞추기
        </button>
        <button className={btn} onClick={relayout} title="위치를 자동 배치로 되돌립니다">
          자동 배치
        </button>
        <span className="mx-1 h-5 w-px bg-line" />
        <GenerateButton disabled={!schema || generating} generating={generating} onPick={(mode) => void generate(mode)} />
        <button className={btn} disabled={!schema || generating} onClick={() => setFilesOpen(true)}>
          온톨로지 불러오기{files.length > 0 ? ` (${files.length})` : ''}
        </button>
      </div>
    </header>
  )
}
