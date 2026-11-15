import { useEffect, useState } from 'react'
import { api } from '../api'
import { useStore } from '../store'
import type { Diff, OntologyFile } from '../types'

const STATUS: Record<string, { label: string; tone: string }> = {
  added: { label: '새로 생김', tone: 'bg-emerald-100 text-emerald-800' },
  removed: { label: '삭제됨', tone: 'bg-rose-100 text-rose-800' },
  changed: { label: '바뀜', tone: 'bg-amber-100 text-amber-800' },
}

/** 지금 작업본과 자동 생성 원본(또는 다른 버전)의 차이. 주어별로 추가(+)·삭제(−)된 트리플을 보여준다. */
export function DiffDialog() {
  const open = useStore((s) => s.diffOpen)
  const db = useStore((s) => s.db)
  const ontology = useStore((s) => s.ontology)
  const setOpen = useStore((s) => s.setDiffOpen)
  const select = useStore((s) => s.select)
  const [versions, setVersions] = useState<OntologyFile[]>([])
  const [against, setAgainst] = useState<string | undefined>(undefined)
  const [diff, setDiff] = useState<Diff | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!open || !db) return
    void api.versions(db).then(setVersions)
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false)
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, db, setOpen])

  useEffect(() => {
    if (!open || !db) return
    setError(null)
    api.diff(db, against).then(setDiff, (e: Error) => setError(e.message))
  }, [open, db, against, ontology])

  if (!open) return null
  const origin = versions.find((v) => v.filename === v.origin)
  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-slate-900/40 p-4" onClick={() => setOpen(false)}>
      <div role="dialog" aria-modal="true" aria-label="변경 내용" className="flex max-h-[85vh] w-[860px] max-w-full flex-col rounded-xl bg-white shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-start justify-between gap-3 border-b border-line px-5 py-3">
          <div className="min-w-0">
            <h2 className="text-[14px] font-semibold">변경 내용 (diff)</h2>
            <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[11.5px] text-muted">
              <span>비교 대상</span>
              <select aria-label="비교할 버전" className="max-w-[360px] rounded border border-line px-1.5 py-0.5 font-mono text-[11px]" value={against ?? ''} onChange={(e) => setAgainst(e.target.value || undefined)}>
                <option value="">자동 생성 원본{origin ? ` (${origin.filename})` : ''}</option>
                {versions
                  .filter((v) => v.filename !== v.origin)
                  .map((v) => (
                    <option key={v.filename} value={v.filename}>
                      수정본 {v.filename}
                      {v.note ? ` · ${v.note}` : ''}
                    </option>
                  ))}
              </select>
              <span>→ 지금 작업본</span>
              {diff && diff.unsaved_changes > 0 && <span className="rounded bg-amber-100 px-1.5 text-amber-800">저장 안 한 수정 {diff.unsaved_changes}건 포함</span>}
            </div>
          </div>
          <button className="rounded px-2 py-1 text-muted hover:bg-slate-100" aria-label="닫기" onClick={() => setOpen(false)}>
            ✕
          </button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-3">
          {error && <p className="text-[12px] text-red-700">{error}</p>}
          {!diff && !error && <p className="text-[12px] text-muted">비교하는 중…</p>}
          {diff && (
            <>
              <p className="mb-3 text-[12px] text-slate-600">
                요소 {diff.summary.subjects}개 · 추가 <span className="font-semibold text-emerald-700">+{diff.summary.added}</span> · 삭제 <span className="font-semibold text-rose-700">−{diff.summary.removed}</span>
              </p>
              {diff.items.length === 0 && <div className="rounded-lg border border-dashed border-line px-4 py-8 text-center text-[12px] text-muted">차이가 없습니다.</div>}
              <ul className="space-y-2">
                {diff.items.map((it) => (
                  <li key={it.iri} className="rounded-lg border border-line">
                    <div className="flex items-center gap-2 border-b border-slate-100 px-3 py-1.5">
                      <span className={`rounded px-1.5 py-0.5 text-[10px] font-semibold ${STATUS[it.status].tone}`}>{STATUS[it.status].label}</span>
                      <button
                        className="font-mono text-[12px] font-medium text-onto hover:underline disabled:text-ink disabled:no-underline"
                        disabled={it.status === 'removed'}
                        onClick={() => {
                          const o = ontology
                          const kind = o?.classes.some((c) => c.iri === it.iri) ? 'class' : o?.object_properties.some((p) => p.iri === it.iri) ? 'objprop' : o?.data_properties.some((p) => p.iri === it.iri) ? 'dataprop' : null
                          if (kind) (select({ kind, iri: it.iri }), setOpen(false))
                        }}
                      >
                        {it.name}
                      </button>
                    </div>
                    <table className="w-full table-fixed border-collapse font-mono text-[11px]">
                      <tbody>
                        {it.removed.map(([p, o], i) => (
                          <tr key={`r${i}`} className="bg-rose-50/70 align-top text-rose-900">
                            <td className="w-6 py-0.5 pl-3">−</td>
                            <td className="w-[28%] break-all py-0.5 pr-2">{p}</td>
                            <td className="break-words py-0.5 pr-3">{o}</td>
                          </tr>
                        ))}
                        {it.added.map(([p, o], i) => (
                          <tr key={`a${i}`} className="bg-emerald-50/70 align-top text-emerald-900">
                            <td className="w-6 py-0.5 pl-3">+</td>
                            <td className="w-[28%] break-all py-0.5 pr-2">{p}</td>
                            <td className="break-words py-0.5 pr-3">{o}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
