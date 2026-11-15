/** 오른쪽 패널의 수정 입력 부품. 저장하면 store.edit 로 연산을 보내고, 백엔드 검사를 통과해야 반영된다. */
import { useState, type ReactNode } from 'react'
import { useStore } from '../store'
import type { OntClass, Ontology, Triple } from '../types'

const ONT = 'http://example.org/ontology#'
export const shortIri = (iri: string) => (iri.startsWith(ONT) ? `ont:${iri.slice(ONT.length)}` : iri)

const input = 'w-full rounded border border-line px-2 py-1 text-[12px] focus:border-onto focus:outline-none'
const smallBtn = 'rounded border border-line px-2 py-0.5 text-[11px] hover:bg-slate-50 disabled:opacity-40'
const primary = 'rounded bg-onto px-2 py-0.5 text-[11px] font-medium text-white hover:brightness-110 disabled:opacity-40'

export const XSD_TYPES = ['xsd:string', 'xsd:integer', 'xsd:decimal', 'xsd:double', 'xsd:boolean', 'xsd:date', 'xsd:dateTime', 'xsd:time', 'xsd:gYear']

function EditButton({ onClick, title }: { onClick: () => void; title: string }) {
  const busy = useStore((s) => s.editing)
  return (
    <button type="button" disabled={busy} onClick={onClick} title={title} aria-label={title} className="shrink-0 rounded px-1.5 text-[11px] text-onto hover:bg-onto-soft disabled:opacity-40">
      ✎ 수정
    </button>
  )
}

/** 글자 값 하나 (라벨, 설명, 이름 등). 보기 ↔ 입력 전환 */
export function EditableText({ value, onSave, multiline, mono, placeholder, hint, display }: { value: string; onSave: (v: string) => Promise<boolean>; multiline?: boolean; mono?: boolean; placeholder?: string; hint?: string; display?: ReactNode }) {
  const [draft, setDraft] = useState<string | null>(null)
  const busy = useStore((s) => s.editing)
  if (draft === null) {
    return (
      <div className="flex items-start gap-2">
        <div className={`min-w-0 flex-1 break-words text-[12px] leading-relaxed ${mono ? 'font-mono' : ''}`}>{display ?? (value || <span className="text-slate-400">{placeholder ?? '없음'}</span>)}</div>
        <EditButton onClick={() => setDraft(value)} title="수정" />
      </div>
    )
  }
  const save = async () => {
    if (draft.trim() === value.trim()) return setDraft(null)
    if (await onSave(draft)) setDraft(null)
  }
  return (
    <div className="space-y-1">
      {multiline ? (
        <textarea autoFocus rows={4} value={draft} onChange={(e) => setDraft(e.target.value)} placeholder={placeholder} className={`${input} leading-snug`} />
      ) : (
        <input
          autoFocus
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.nativeEvent.isComposing) void save()
            if (e.key === 'Escape') setDraft(null)
          }}
          placeholder={placeholder}
          className={`${input} ${mono ? 'font-mono' : ''}`}
        />
      )}
      {hint && <p className="text-[11px] leading-snug text-muted">{hint}</p>}
      <div className="flex gap-1">
        <button type="button" className={primary} disabled={busy} onClick={() => void save()}>
          적용
        </button>
        <button type="button" className={smallBtn} onClick={() => setDraft(null)}>
          취소
        </button>
      </div>
    </div>
  )
}

/** 클래스 목록 (상위 클래스, 도메인, 범위). 칩으로 보여주고 × 로 빼고 목록에서 골라 넣는다 */
export function ClassListEditor({ values, classes, onSave, onPick, exclude, emptyText = '없음' }: { values: string[]; classes: OntClass[]; onSave: (v: string[]) => Promise<boolean>; onPick: (iri: string) => void; exclude?: string; emptyText?: string }) {
  const [editing, setEditing] = useState(false)
  const busy = useStore((s) => s.editing)
  const name = (iri: string) => classes.find((c) => c.iri === iri)?.name ?? shortIri(iri)
  const options = classes.filter((c) => !c.external && c.iri !== exclude && !values.includes(c.iri))
  return (
    <div className="flex flex-wrap items-center gap-1">
      {values.length === 0 && <span className="text-[12px] text-slate-400">{emptyText}</span>}
      {values.map((v) => (
        <span key={v} className="inline-flex items-center rounded-full border border-onto/50 bg-white text-[11px]">
          <button type="button" className="px-2 py-0.5 font-mono text-onto hover:underline" onClick={() => onPick(v)}>
            {name(v)}
          </button>
          {editing && (
            <button type="button" disabled={busy} className="pr-1.5 text-muted hover:text-red-700" aria-label={`${name(v)} 빼기`} onClick={() => void onSave(values.filter((x) => x !== v))}>
              ×
            </button>
          )}
        </span>
      ))}
      {editing ? (
        <>
          <select
            aria-label="클래스 추가"
            className="rounded border border-line px-1 py-0.5 text-[11px]"
            value=""
            disabled={busy}
            onChange={(e) => e.target.value && void onSave([...values, e.target.value])}
          >
            <option value="">+ 추가…</option>
            {options.map((c) => (
              <option key={c.iri} value={c.iri}>
                {c.name}
              </option>
            ))}
          </select>
          <button type="button" className={smallBtn} onClick={() => setEditing(false)}>
            완료
          </button>
        </>
      ) : (
        <EditButton onClick={() => setEditing(true)} title="목록 수정" />
      )}
    </div>
  )
}

/** 이 클래스에서 나가는 새 관계(객체 속성) 추가 */
export function AddRelation({ domain, ontology }: { domain: OntClass; ontology: Ontology }) {
  const edit = useStore((s) => s.edit)
  const busy = useStore((s) => s.editing)
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')
  const [range, setRange] = useState('')
  const [label, setLabel] = useState('')
  const [comment, setComment] = useState('')
  if (!open) {
    return (
      <button type="button" className={`${smallBtn} mt-1`} onClick={() => (setOpen(true), setName(`${domain.source?.table ?? domain.name.toLowerCase()}_has`))}>
        + 관계 추가
      </button>
    )
  }
  const submit = async () => {
    const ok = await edit([{ op: 'add_object_property', name: name.trim(), domain: domain.iri, range, label: label.trim() || undefined, comment: comment.trim() || undefined }])
    if (ok) {
      setOpen(false)
      setName('')
      setRange('')
      setLabel('')
      setComment('')
    }
  }
  return (
    <div className="mt-2 space-y-1.5 rounded-lg border border-onto/40 bg-onto-soft/40 p-2">
      <div className="text-[11px] font-semibold text-onto">새 관계: {domain.name} → ?</div>
      <input value={name} onChange={(e) => setName(e.target.value)} placeholder="이름 (영문, 예: film_hasDirector)" aria-label="관계 이름" className={`${input} font-mono`} />
      <select value={range} onChange={(e) => setRange(e.target.value)} aria-label="범위 클래스" className={input}>
        <option value="">범위 클래스 선택…</option>
        {ontology.classes
          .filter((c) => !c.external)
          .map((c) => (
            <option key={c.iri} value={c.iri}>
              {c.name}
            </option>
          ))}
      </select>
      <input value={label} onChange={(e) => setLabel(e.target.value)} placeholder="라벨 (선택)" aria-label="관계 라벨" className={input} />
      <input value={comment} onChange={(e) => setComment(e.target.value)} placeholder="설명 (선택)" aria-label="관계 설명" className={input} />
      <p className="text-[11px] leading-snug text-muted">출처 컬럼이 없는 관계는 에이전트가 SQL로 옮길 근거가 약합니다. 저장 시 경고로 표시됩니다.</p>
      <div className="flex gap-1">
        <button type="button" className={primary} disabled={busy || !name.trim() || !range} onClick={() => void submit()}>
          추가
        </button>
        <button type="button" className={smallBtn} onClick={() => setOpen(false)}>
          취소
        </button>
      </div>
    </div>
  )
}

const tripleOp = (op: 'add_triple' | 'remove_triple', s: string, r: Pick<Triple, 'p_iri' | 'o' | 'o_iri' | 'kind' | 'lang' | 'datatype'>) => ({
  op,
  s,
  p: r.p_iri,
  o: r.kind === 'iri' ? r.o_iri : r.o,
  kind: r.kind,
  lang: r.lang,
  datatype: r.datatype,
})

const COMMON_PREDICATES = ['rdfs:label', 'rdfs:comment', 'rdfs:seeAlso', 'rdfs:subClassOf', 'rdfs:domain', 'rdfs:range', 'owl:inverseOf', 'owl:equivalentClass', 'skos:altLabel', 'skos:example']

/** 트리플 표 (주어 – 속성 – 값). 행마다 수정·삭제, 아래에서 새 트리플 추가 */
export function TripleEditor({ subject, rows }: { subject: { iri: string; name: string }; rows: Triple[] }) {
  const edit = useStore((s) => s.edit)
  const busy = useStore((s) => s.editing)
  const [editRow, setEditRow] = useState<number | null>(null)
  const [draft, setDraft] = useState('')
  const [adding, setAdding] = useState(false)
  const [p, setP] = useState('rdfs:comment')
  const [o, setO] = useState('')
  const [kind, setKind] = useState<'literal' | 'iri'>('literal')

  const replace = async (r: Triple) => {
    const ok = await edit([tripleOp('remove_triple', subject.iri, r), { ...tripleOp('add_triple', subject.iri, r), o: draft.trim() }])
    if (ok) setEditRow(null)
  }
  const add = async () => {
    const ok = await edit([{ op: 'add_triple', s: subject.iri, p: p.trim(), o: o.trim(), kind }])
    if (ok) (setO(''), setAdding(false))
  }

  return (
    <div>
      <table className="w-full table-fixed border-collapse text-[11px]">
        <thead>
          <tr className="text-left text-muted">
            <th className="w-[22%] border-b border-line py-1 pr-2 font-medium">주어</th>
            <th className="w-[28%] border-b border-line py-1 pr-2 font-medium">속성</th>
            <th className="border-b border-line py-1 font-medium">값</th>
            <th className="w-[38px] border-b border-line" />
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={`${r.p}|${r.o}|${i}`} className="group align-top">
              <td className="break-all border-b border-slate-100 py-1 pr-2 font-mono text-slate-500">{i === 0 ? `ont:${subject.name}` : '〃'}</td>
              <td className="break-all border-b border-slate-100 py-1 pr-2 font-mono text-onto">{r.p}</td>
              <td className={`break-words border-b border-slate-100 py-1 ${r.kind === 'literal' ? 'text-slate-700' : 'font-mono text-slate-800'}`}>
                {editRow === i ? (
                  <div className="space-y-1">
                    <textarea autoFocus rows={2} value={draft} onChange={(e) => setDraft(e.target.value)} className={`${input} text-[11px]`} aria-label="트리플 값" />
                    <div className="flex gap-1">
                      <button type="button" className={primary} disabled={busy || !draft.trim()} onClick={() => void replace(r)}>
                        적용
                      </button>
                      <button type="button" className={smallBtn} onClick={() => setEditRow(null)}>
                        취소
                      </button>
                    </div>
                  </div>
                ) : r.kind === 'literal' ? (
                  `"${r.o}"${r.lang ? `@${r.lang}` : ''}`
                ) : (
                  r.o
                )}
              </td>
              <td className="border-b border-slate-100 py-1 text-right">
                {r.kind !== 'expr' && editRow !== i && (
                  <span className="invisible inline-flex group-hover:visible group-focus-within:visible">
                    <button type="button" disabled={busy} title="값 수정" aria-label="값 수정" className="rounded px-0.5 text-onto hover:bg-onto-soft" onClick={() => (setEditRow(i), setDraft(r.kind === 'iri' ? (r.o_iri ?? r.o) : r.o))}>
                      ✎
                    </button>
                    <button type="button" disabled={busy} title="트리플 삭제" aria-label="트리플 삭제" className="rounded px-0.5 text-red-700 hover:bg-red-50" onClick={() => void edit([tripleOp('remove_triple', subject.iri, r)])}>
                      ×
                    </button>
                  </span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {adding ? (
        <div className="mt-2 space-y-1 rounded-lg border border-line p-2">
          <input list="common-predicates" value={p} onChange={(e) => setP(e.target.value)} placeholder="속성 (예: rdfs:comment)" aria-label="새 트리플 속성" className={`${input} font-mono`} />
          <datalist id="common-predicates">
            {COMMON_PREDICATES.map((x) => (
              <option key={x} value={x} />
            ))}
          </datalist>
          <div className="flex gap-1">
            <select value={kind} onChange={(e) => setKind(e.target.value as 'literal' | 'iri')} aria-label="값 종류" className="rounded border border-line px-1 text-[11px]">
              <option value="literal">글자</option>
              <option value="iri">IRI</option>
            </select>
            <input value={o} onChange={(e) => setO(e.target.value)} placeholder={kind === 'iri' ? 'ont:Film 또는 http://…' : '값'} aria-label="새 트리플 값" className={`${input} ${kind === 'iri' ? 'font-mono' : ''}`} />
          </div>
          <div className="flex gap-1">
            <button type="button" className={primary} disabled={busy || !p.trim() || !o.trim()} onClick={() => void add()}>
              추가
            </button>
            <button type="button" className={smallBtn} onClick={() => setAdding(false)}>
              취소
            </button>
          </div>
        </div>
      ) : (
        <button type="button" className={`${smallBtn} mt-2`} onClick={() => setAdding(true)}>
          + 트리플 추가
        </button>
      )}
    </div>
  )
}
