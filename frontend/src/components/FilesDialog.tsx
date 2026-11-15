import { useEffect, useRef } from 'react'
import { useStore } from '../store'

const KIND: Record<string, string> = { 'direct-mapping': 'Direct Mapping', rigor: 'RIGOR 생성', upload: '업로드', edit: '수정본', unknown: '기타' }

/** 생성하거나 업로드한 온톨로지 파일 목록. 여기서 고른 파일이 화면과 에이전트에 쓰인다. */
export function FilesDialog() {
  const open = useStore((s) => s.filesOpen)
  const files = useStore((s) => s.files)
  const db = useStore((s) => s.db)
  const ontology = useStore((s) => s.ontology)
  const setOpen = useStore((s) => s.setFilesOpen)
  const loadFile = useStore((s) => s.loadFile)
  const uploadFile = useStore((s) => s.uploadFile)
  const unload = useStore((s) => s.unload)
  const input = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false)
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, setOpen])

  if (!open) return null
  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-slate-900/40 p-4" onClick={() => setOpen(false)}>
      <div role="dialog" aria-modal="true" aria-label="온톨로지 불러오기" className="flex max-h-[80vh] w-[680px] max-w-full flex-col rounded-xl bg-white shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between border-b border-line px-5 py-3">
          <div>
            <h2 className="text-[14px] font-semibold">온톨로지 불러오기</h2>
            <p className="text-[11px] text-muted">
              <span className="font-mono">{db}</span>에서 생성하거나 업로드한 파일입니다. 불러온 파일이 화면에 그래프로 나타납니다.
            </p>
          </div>
          <button className="rounded px-2 py-1 text-muted hover:bg-slate-100" aria-label="닫기" onClick={() => setOpen(false)}>
            ✕
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-3">
          {files.length === 0 ? (
            <div className="rounded-lg border border-dashed border-line px-4 py-8 text-center text-[12px] text-muted">
              아직 온톨로지 파일이 없습니다.
              <br />
              상단의 “온톨로지 생성하기”를 누르거나 아래에서 파일을 업로드하세요.
            </div>
          ) : (
            <ul className="space-y-2">
              {files.map((f) => (
                <li key={f.filename} className={`flex items-center gap-3 rounded-lg border px-3 py-2.5 ${f.loaded ? 'border-onto bg-onto-soft/50' : 'border-line'}`}>
                  <div className="min-w-0 flex-1">
                    <div className="truncate font-mono text-[12px] font-medium">{f.filename}</div>
                    <div className="mt-0.5 text-[11px] text-muted">
                      {KIND[f.kind] ?? f.kind}
                      {f.parent ? ` (← ${f.parent})` : ''}
                      {f.note && f.kind === 'edit' ? ` · ${f.note}` : ''} · {f.created_at.replace('T', ' ')} · 클래스 {f.counts.classes} · 데이터 속성 {f.counts.data_properties} · 객체 속성 {f.counts.object_properties}
                    </div>
                  </div>
                  {f.loaded ? (
                    <span className="shrink-0 rounded-md bg-onto px-2.5 py-1 text-[11px] font-medium text-white">불러옴</span>
                  ) : (
                    <button className="shrink-0 rounded-md border border-onto px-2.5 py-1 text-[12px] font-medium text-onto hover:bg-onto hover:text-white" onClick={() => void loadFile(f.filename)}>
                      불러오기
                    </button>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="flex items-center gap-2 border-t border-line px-5 py-3">
          <input
            ref={input}
            type="file"
            accept=".ttl,.owl,.rdf,.xml"
            className="hidden"
            onChange={(e) => {
              const file = e.target.files?.[0]
              if (file) void uploadFile(file)
              e.target.value = ''
            }}
          />
          <button className="rounded-md border border-line px-2.5 py-1 text-[12px] hover:bg-slate-50" onClick={() => input.current?.click()}>
            파일 업로드 (.ttl / .owl)
          </button>
          {ontology && (
            <button className="rounded-md border border-line px-2.5 py-1 text-[12px] hover:bg-slate-50" onClick={() => void unload()}>
              불러온 온톨로지 닫기
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
