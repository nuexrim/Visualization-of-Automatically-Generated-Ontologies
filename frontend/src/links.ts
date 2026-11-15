/** 온톨로지 요소 ↔ ERD 테이블·컬럼 연결. 출처(prov:wasDerivedFrom)로 서로를 찾는다. */
import { useMemo } from 'react'
import { shownOntology, useStore } from './store'
import type { DataProperty, ObjectProperty, OntClass, Ontology, Selection } from './types'

export const columnKey = (table: string, column: string) => `${table}\u0000${column}`

export interface OntologyIndex {
  classByIri: Map<string, OntClass>
  classesByTable: Map<string, OntClass[]>
  objProp: Map<string, ObjectProperty>
  dataProp: Map<string, DataProperty>
  propByColumn: Map<string, { kind: 'objprop' | 'dataprop'; iri: string }>
  dataPropsByClass: Map<string, DataProperty[]>
}

export function indexOntology(o: Ontology): OntologyIndex {
  const idx: OntologyIndex = {
    classByIri: new Map(o.classes.map((c) => [c.iri, c])),
    classesByTable: new Map(),
    objProp: new Map(o.object_properties.map((p) => [p.iri, p])),
    dataProp: new Map(o.data_properties.map((p) => [p.iri, p])),
    propByColumn: new Map(),
    dataPropsByClass: new Map(),
  }
  for (const c of o.classes) {
    if (!c.source) continue
    const list = idx.classesByTable.get(c.source.table) ?? []
    list.push(c)
    idx.classesByTable.set(c.source.table, list)
  }
  for (const p of o.data_properties) {
    if (p.source?.column) idx.propByColumn.set(columnKey(p.source.table, p.source.column), { kind: 'dataprop', iri: p.iri })
    for (const d of p.domains) {
      const list = idx.dataPropsByClass.get(d) ?? []
      list.push(p)
      idx.dataPropsByClass.set(d, list)
    }
  }
  // 같은 컬럼에서 나온 객체 속성이 여럿이면 처음 것을 대표로 쓴다
  for (const p of o.object_properties) {
    if (!p.source?.column) continue
    const key = columnKey(p.source.table, p.source.column)
    if (idx.propByColumn.get(key)?.kind !== 'objprop') idx.propByColumn.set(key, { kind: 'objprop', iri: p.iri })
  }
  return idx
}

/** 컬럼을 골랐는데 대응하는 속성이 있으면 그 속성을 고른 것으로 본다. */
export function resolveSelection(sel: Selection | null, idx: OntologyIndex | null): Selection | null {
  if (sel?.kind === 'column' && idx) {
    const hit = idx.propByColumn.get(columnKey(sel.table, sel.column))
    if (hit) return hit
  }
  return sel
}

export interface Highlight {
  tables: Set<string>
  /** columnKey 형식 */
  columns: Set<string>
  classes: Set<string>
  props: Set<string>
  /** 이 테이블/클래스의 이웃까지 또렷하게 보여준다 */
  focusTable: string | null
  focusClass: string | null
  active: boolean
}

export function computeHighlight(selection: Selection | null, idx: OntologyIndex | null): Highlight {
  const h: Highlight = { tables: new Set(), columns: new Set(), classes: new Set(), props: new Set(), focusTable: null, focusClass: null, active: false }
  const sel = resolveSelection(selection, idx)
  if (!sel) return h
  h.active = true
  const addClass = (iri: string) => {
    h.classes.add(iri)
    const t = idx?.classByIri.get(iri)?.source?.table
    if (t) h.tables.add(t)
  }
  switch (sel.kind) {
    case 'table': {
      h.tables.add(sel.table)
      h.focusTable = sel.table
      const classes = idx?.classesByTable.get(sel.table) ?? []
      for (const c of classes) h.classes.add(c.iri)
      h.focusClass = classes[0]?.iri ?? null
      break
    }
    case 'column':
      h.tables.add(sel.table)
      h.columns.add(columnKey(sel.table, sel.column))
      break
    case 'class': {
      addClass(sel.iri)
      h.focusClass = sel.iri
      h.focusTable = idx?.classByIri.get(sel.iri)?.source?.table ?? null
      break
    }
    case 'objprop':
    case 'dataprop': {
      const p = sel.kind === 'objprop' ? idx?.objProp.get(sel.iri) : idx?.dataProp.get(sel.iri)
      h.props.add(sel.iri)
      if (!p) break
      p.domains.forEach(addClass)
      if (sel.kind === 'objprop') p.ranges.forEach(addClass)
      if (p.source) {
        h.tables.add(p.source.table)
        if (p.source.column) h.columns.add(columnKey(p.source.table, p.source.column))
      }
      break
    }
  }
  return h
}

export function useOntologyIndex(): OntologyIndex | null {
  const ontology = useStore(shownOntology)
  return useMemo(() => (ontology ? indexOntology(ontology) : null), [ontology])
}

export function useHighlight(): Highlight {
  const selection = useStore((s) => s.selection)
  const idx = useOntologyIndex()
  return useMemo(() => computeHighlight(selection, idx), [selection, idx])
}
