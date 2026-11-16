import { columnKey, useOntologyIndex } from '../links'
import { showsOntology, useStore } from '../store'

/** 컬럼에 마우스를 올리면 database_description의 설명을 보여준다. "ERD + 온톨로지" 보기에서는 대응하는 온톨로지 속성도 함께. */
export function ColumnTooltip() {
  const tip = useStore((s) => s.tip)
  const withOntology = useStore(showsOntology)
  const idx = useOntologyIndex()
  if (!tip) return null
  const hit = withOntology && idx ? idx.propByColumn.get(columnKey(tip.table, tip.column.name)) : undefined
  const prop = hit && idx ? (hit.kind === 'objprop' ? idx.objProp.get(hit.iri) : idx.dataProp.get(hit.iri)) : undefined
  const comment = prop?.comments[prop.comments.length - 1]
  const { column: c } = tip
  const W = 320
  const left = Math.min(tip.x + 14, window.innerWidth - W - 12)
  const top = Math.min(tip.y + 16, window.innerHeight - 160)
  return (
    <div style={{ left, top, width: W }} className="pointer-events-none fixed z-50 rounded-md border border-slate-700 bg-slate-900 p-3 text-[12px] leading-relaxed text-slate-100 shadow-xl">
      <div className="mb-1 flex items-baseline justify-between gap-2">
        <span className="truncate font-mono font-semibold">
          {tip.table}.{c.name}
        </span>
        <span className="shrink-0 font-mono text-[10px] text-slate-400">
          {c.type}
          {c.nullable ? '' : ' · NOT NULL'}
        </span>
      </div>
      {c.label && c.label.toLowerCase() !== c.name.toLowerCase() && <div className="text-slate-300">{c.label}</div>}
      <div className={c.description ? '' : 'text-slate-400'}>{c.description || '설명 없음 (BIRD 원본에 비어 있음)'}</div>
      {c.value_description && <div className="mt-1.5 whitespace-pre-line border-t border-slate-700 pt-1.5 text-slate-300">{c.value_description}</div>}
      {c.fk && (
        <div className="mt-1.5 border-t border-slate-700 pt-1.5 font-mono text-[11px] text-blue-300">
          → {c.fk.table}.{c.fk.column}
        </div>
      )}
      {prop && (
        <div className="mt-1.5 border-t border-teal-700/70 pt-1.5">
          <div className="text-[10px] font-semibold uppercase tracking-wide text-teal-300">온톨로지 {hit?.kind === 'objprop' ? '관계' : '데이터 속성'}</div>
          <div className="font-mono text-[11px] text-teal-200">ont:{prop.name}</div>
          {prop.label && <div className="text-teal-100">{prop.label}</div>}
          {comment && <div className="text-slate-300">{comment}</div>}
          {'value_description' in prop && prop.value_description && <div className="mt-1 whitespace-pre-line text-slate-300">{prop.value_description}</div>}
        </div>
      )}
    </div>
  )
}
