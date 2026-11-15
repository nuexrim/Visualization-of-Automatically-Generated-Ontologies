import { useEffect, useState } from 'react'
import { ErdCanvas } from './canvas/ErdCanvas'
import { OntologyCanvas } from './canvas/OntologyCanvas'
import { TraceQuery } from './canvas/TraceQuery'
import { ChatPanel } from './chat/ChatPanel'
import { ColumnTooltip } from './components/ColumnTooltip'
import { DiffDialog } from './components/DiffDialog'
import { FilesDialog } from './components/FilesDialog'
import { NoticeBar } from './components/NoticeBar'
import { TopBar } from './components/TopBar'
import { RightPanel } from './panels/RightPanel'
import { useStore } from './store'

function PaneLabel({ children }: { children: string }) {
  return <div className="pointer-events-none absolute left-3 top-3 z-10 rounded bg-white/90 px-2 py-0.5 text-[11px] font-semibold text-muted shadow-sm">{children}</div>
}

export default function App() {
  const init = useStore((s) => s.init)
  const view = useStore((s) => s.view)
  const importDb = useStore((s) => s.importDb)
  const [dragging, setDragging] = useState(false)
  useEffect(() => {
    void init()
  }, [init])
  // 되돌리기 ⌘Z / 다시하기 ⇧⌘Z (입력 칸에 있을 때는 브라우저 기본 동작)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!(e.metaKey || e.ctrlKey) || e.key.toLowerCase() !== 'z') return
      const t = e.target as HTMLElement
      if (t.closest('input, textarea, select, [contenteditable="true"]')) return
      e.preventDefault()
      const { undo, redo } = useStore.getState()
      void (e.shiftKey ? redo() : undo())
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  return (
    <div className="flex h-full flex-col">
      <TopBar />
      <div className="flex min-h-0 flex-1">
        <main
          className="relative flex min-w-0 flex-1"
          onDragOver={(e) => {
            if (!e.dataTransfer.types.includes('Files')) return
            e.preventDefault()
            setDragging(true)
          }}
          onDragLeave={(e) => {
            if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setDragging(false)
          }}
          onDrop={(e) => {
            if (!e.dataTransfer.types.includes('Files')) return
            e.preventDefault()
            setDragging(false)
            const file = e.dataTransfer.files[0]
            if (file) void importDb(file)
          }}
        >
          <NoticeBar />
          {dragging && (
            <div className="pointer-events-none absolute inset-3 z-30 flex items-center justify-center rounded-2xl border-2 border-dashed border-accent bg-blue-50/80 text-[15px] font-semibold text-accent">
              여기에 놓으면 DB 파일을 불러옵니다
            </div>
          )}
          {view !== 'onto' && (
            <div className="relative min-w-0 flex-1">
              {view === 'split' && <PaneLabel>ERD</PaneLabel>}
              <ErdCanvas overlay={view === 'overlay'} />
              <TraceQuery pane="erd" />
            </div>
          )}
          {(view === 'onto' || view === 'split') && (
            <div className={`relative min-w-0 flex-1 ${view === 'split' ? 'border-l border-line' : ''}`}>
              {view === 'split' && <PaneLabel>온톨로지</PaneLabel>}
              <OntologyCanvas />
              <TraceQuery pane="onto" />
            </div>
          )}
        </main>
        <RightPanel />
      </div>
      <ChatPanel />
      <ColumnTooltip />
      <FilesDialog />
      <DiffDialog />
    </div>
  )
}
