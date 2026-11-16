import type { ReactNode } from 'react'
import { columnKey, resolveSelection, useOntologyIndex, type OntologyIndex } from '../links'
import { showsOntology, useStore } from '../store'
import { AddRelation, ClassListEditor, EditableText, TripleEditor, XSD_TYPES } from './EditFields'
import { GenerationPanel } from './GenerationPanel'
import type { Entity, Issue, Ontology, Schema, Selection, Table } from '../types'

const shell = 'w-[360px] shrink-0 overflow-y-auto border-l border-line bg-white'
const h3 = 'mb-2 text-[11px] font-semibold uppercase tracking-wide text-muted'
const link = 'rounded px-1.5 py-1 text-left hover:bg-slate-100'

function Header({ title, subtitle, tone }: { title: ReactNode; subtitle: ReactNode; tone: 'erd' | 'onto' }) {
  const select = useStore((s) => s.select)
  return (
    <div className={`sticky top-0 z-10 border-b border-line px-4 py-3 ${tone === 'onto' ? 'bg-onto-soft' : 'bg-white'}`}>
      <div className="flex items-start justify-between gap-2">
        <h2 className="min-w-0 break-words text-[14px] font-semibold">{title}</h2>
        <button className="rounded px-1.5 text-muted hover:bg-black/5" onClick={() => select(null)} aria-label="선택 해제">
          ✕
        </button>
      </div>
      <div className="mt-0.5 text-[11px] text-muted">{subtitle}</div>
    </div>
  )
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="border-t border-line px-4 py-3 first:border-t-0">
      <h3 className={h3}>{title}</h3>
      {children}
    </section>
  )
}

const none = <div className="text-[12px] text-slate-400">없음</div>

// ---------------------------------------------------------------- ERD 쪽

function IssueSummary({ ontology }: { ontology: Ontology }) {
  const issues = useStore((s) => s.issues)
  const select = useStore((s) => s.select)
  const errors = issues.filter((i) => i.level === 'error')
  const warnings = issues.filter((i) => i.level === 'warning')
  const kindOf = (iri: string): Selection | null =>
    ontology.classes.some((c) => c.iri === iri) ? { kind: 'class', iri } : ontology.object_properties.some((p) => p.iri === iri) ? { kind: 'objprop', iri } : ontology.data_properties.some((p) => p.iri === iri) ? { kind: 'dataprop', iri } : null
  return (
    <div className="mt-3 rounded-lg border border-line px-3 py-2">
      <div className="text-[12px] font-semibold">
        검사 결과 <span className={errors.length ? 'text-red-700' : 'text-onto'}>오류 {errors.length}</span> · <span className={warnings.length ? 'text-amber-700' : 'text-muted'}>경고 {warnings.length}</span>
      </div>
      <p className="mt-0.5 text-[11px] leading-snug text-muted">도메인·범위 클래스, 출처 테이블·컬럼, 이름 충돌, 상위 클래스 순환을 검사합니다. 수정으로 새 오류가 생기면 적용되지 않습니다.</p>
      {[...errors, ...warnings].slice(0, 8).map((i) => (
        <button key={i.code + i.message} className={`mt-1 block w-full text-left text-[11.5px] leading-snug hover:underline ${i.level === 'error' ? 'text-red-700' : 'text-amber-700'}`} onClick={() => {
          const sel = kindOf(i.iri)
          if (sel) select(sel)
        }}>
          {i.message}
        </button>
      ))}
    </div>
  )
}

function Overview({ schema, ontology, loaded }: { schema: Schema; ontology: Ontology | null; loaded: boolean }) {
  const select = useStore((s) => s.select)
  return (
    <aside className={`${shell} p-4`}>
      <h2 className="mb-1 text-[13px] font-semibold">테이블 {schema.tables.length}개</h2>
      <p className="mb-3 text-[12px] text-muted">테이블을 선택하면 컬럼 설명과 외래 키를 볼 수 있습니다.</p>
      <ul className="space-y-0.5">
        {schema.tables.map((t) => (
          <li key={t.name}>
            <button className="flex w-full items-baseline justify-between rounded px-2 py-1 text-left hover:bg-slate-100" onClick={() => select({ kind: 'table', table: t.name })}>
              <span className="font-mono text-[12px]">{t.name}</span>
              <span className="text-[11px] text-muted">
                컬럼 {t.columns.length} · {t.row_count.toLocaleString()}행
              </span>
            </button>
          </li>
        ))}
      </ul>
      {ontology ? (
        <div className="mt-5 border-t border-line pt-4">
          <h2 className="mb-1 text-[13px] font-semibold">온톨로지</h2>
          <p className="mb-2 break-all font-mono text-[11px] text-onto">{ontology.filename}</p>
          <p className="text-[12px] text-muted">
            클래스 {ontology.counts.classes} · 데이터 속성 {ontology.counts.data_properties} · 객체 속성 {ontology.counts.object_properties} · 트리플 {ontology.counts.triples}
          </p>
          {(ontology.history?.changes ?? 0) > 0 && <p className="mt-1 text-[11.5px] text-amber-700">저장하지 않은 수정 {ontology.history?.changes}건이 있습니다. 에이전트는 이미 수정된 내용을 사용합니다.</p>}
          <IssueSummary ontology={ontology} />
          <p className="mt-2 text-[11.5px] text-muted">클래스나 관계를 고르면 오른쪽 패널에서 라벨, 설명, 상위 클래스, 도메인·범위, 트리플을 수정할 수 있습니다.</p>
          <ul className="mt-2 space-y-0.5">
            {ontology.classes.map((c) => (
              <li key={c.iri}>
                <button className="flex w-full items-baseline justify-between rounded px-2 py-1 text-left hover:bg-onto-soft" onClick={() => select({ kind: 'class', iri: c.iri })}>
                  <span className="text-[12px]">{c.label || c.name}</span>
                  <span className="font-mono text-[11px] text-muted">{c.source?.table ?? ''}</span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      ) : loaded ? (
        <p className="mt-5 border-t border-line pt-4 text-[12px] text-muted">이 보기는 DB 구조만 보여줍니다. 온톨로지로 더 알게 된 정보는 “ERD + 온톨로지” 보기에서 볼 수 있습니다.</p>
      ) : (
        <p className="mt-5 border-t border-line pt-4 text-[12px] text-muted">“온톨로지 생성하기”로 파일을 만든 뒤 불러오면 클래스와 관계를 볼 수 있습니다.</p>
      )}
    </aside>
  )
}

function TablePanel({ table, schema, idx, column }: { table: Table; schema: Schema; idx: OntologyIndex | null; column?: string }) {
  const select = useStore((s) => s.select)
  const outgoing = schema.foreign_keys.filter((f) => f.from_table === table.name)
  const incoming = schema.foreign_keys.filter((f) => f.to_table === table.name)
  const classes = idx?.classesByTable.get(table.name) ?? []
  return (
    <aside className={shell}>
      <Header
        tone="erd"
        title={<span className="font-mono">{table.name}</span>}
        subtitle={`테이블 · 컬럼 ${table.columns.length} · ${table.row_count.toLocaleString()}행 · 기본 키 ${table.primary_key.length ? table.primary_key.join(', ') : '없음'}`}
      />
      {classes.length > 0 && (
        <Section title="대응하는 온톨로지 클래스">
          {classes.map((c) => (
            <button key={c.iri} className="mr-1 rounded-full border border-onto/60 px-2.5 py-0.5 text-[11px] font-semibold text-onto hover:bg-onto-soft" onClick={() => select({ kind: 'class', iri: c.iri })}>
              ◆ {c.label || c.name}
            </button>
          ))}
        </Section>
      )}
      <Section title="컬럼">
        <ul className="space-y-2.5">
          {table.columns.map((c) => (
            <li key={c.name} className={c.name === column ? '-mx-1.5 rounded bg-amber-100 px-1.5 py-1' : ''}>
              <div className="flex items-baseline gap-1.5">
                <span className={`font-mono text-[12px] ${c.pk ? 'font-semibold' : ''}`}>{c.name}</span>
                {c.pk && <span className="rounded bg-amber-100 px-1 text-[9px] font-bold text-pk">PK</span>}
                {c.fk && <span className="rounded bg-blue-100 px-1 text-[9px] font-bold text-fk">FK</span>}
                <span className="ml-auto font-mono text-[10px] text-muted">{c.type}</span>
              </div>
              <div className="text-[12px] leading-snug text-slate-600">{c.description || <span className="text-slate-400">설명 없음</span>}</div>
              {c.value_description && <div className="mt-0.5 whitespace-pre-line rounded bg-slate-50 px-1.5 py-1 text-[11px] leading-snug text-slate-500">{c.value_description}</div>}
              {idx && <OntoColumnInfo table={table.name} column={c.name} idx={idx} />}
            </li>
          ))}
        </ul>
      </Section>
      {[
        { title: '참조하는 테이블 (나가는 외래 키)', list: outgoing },
        { title: '참조받는 테이블 (들어오는 외래 키)', list: incoming },
      ].map(({ title, list }) => (
        <Section key={title} title={`${title} · ${list.length}`}>
          {list.length === 0
            ? none
            : list.map((f) => (
                <button key={`${f.from_table}.${f.name}`} className={`${link} block w-full font-mono text-[11px]`} onClick={() => select({ kind: 'column', table: f.from_table, column: f.from_column })}>
                  {f.from_table}.{f.from_column} → {f.to_table}.{f.to_column}
                </button>
              ))}
        </Section>
      ))}
    </aside>
  )
}

/** "ERD + 온톨로지" 보기: 컬럼에 대응하는 온톨로지 속성 (라벨, 설명, 코드값 설명). 누르면 그 속성을 고쳐 쓸 수 있다. */
function OntoColumnInfo({ table, column, idx }: { table: string; column: string; idx: OntologyIndex }) {
  const select = useStore((s) => s.select)
  const hit = idx.propByColumn.get(columnKey(table, column))
  const p = hit && (hit.kind === 'objprop' ? idx.objProp.get(hit.iri) : idx.dataProp.get(hit.iri))
  if (!hit || !p) return null
  const comment = p.comments[p.comments.length - 1]
  return (
    <button className="mt-1 block w-full rounded border border-onto/25 bg-onto-soft/60 px-1.5 py-1 text-left hover:border-onto/60" onClick={() => select(hit)} title="이 속성 보기·수정">
      <div className="flex items-baseline gap-1.5">
        <span className="text-[10px] font-semibold text-onto">◆ {hit.kind === 'objprop' ? '관계' : '속성'}</span>
        <span className="min-w-0 truncate text-[12px] font-medium text-onto">{p.label || p.name}</span>
        <span className="ml-auto shrink-0 font-mono text-[10px] text-muted">ont:{p.name}</span>
      </div>
      {comment && <div className="text-[11.5px] leading-snug text-slate-600">{comment}</div>}
      {'value_description' in p && p.value_description && <div className="mt-0.5 whitespace-pre-line text-[11px] leading-snug text-slate-500">{p.value_description}</div>}
    </button>
  )
}

// ---------------------------------------------------------------- 온톨로지 쪽

/** 설명: 가장 자세한 것을 수정 칸에, 나머지(자동 생성 문구)는 흐리게. 수정하면 설명이 하나로 합쳐진다 */
function Comments({ e }: { e: Entity }) {
  const edit = useStore((s) => s.edit)
  const [main = '', ...rest] = [...e.comments].reverse()
  return (
    <div className="space-y-1.5">
      <EditableText
        value={main}
        multiline
        placeholder="설명 없음"
        hint={rest.length ? `적용하면 아래 흐린 설명 ${rest.length}개는 지워지고 이 설명 하나만 남습니다.` : undefined}
        onSave={(v) => edit([{ op: 'set_comment', iri: e.iri, value: v }])}
      />
      {rest.map((c) => (
        <p key={c} className="text-[12px] leading-relaxed text-slate-400">
          {c}
        </p>
      ))}
    </div>
  )
}

function LabelField({ e }: { e: Entity }) {
  const edit = useStore((s) => s.edit)
  return <EditableText value={e.label} placeholder="라벨 없음" onSave={(v) => edit([{ op: 'set_label', iri: e.iri, value: v }])} />
}

function NameField({ e }: { e: Entity }) {
  const edit = useStore((s) => s.edit)
  return (
    <EditableText
      value={e.name}
      mono
      hint="IRI 이름을 바꾸면 이 요소를 가리키는 모든 트리플이 함께 바뀝니다. 영문, 숫자, _, - 만 쓸 수 있습니다."
      display={<span className="font-mono">ont:{e.name}</span>}
      onSave={(v) => edit([{ op: 'rename', iri: e.iri, name: v.trim() }])}
    />
  )
}

/** 이 요소에 대한 검사 결과 (오류·경고) */
function IssueList({ iri }: { iri: string }) {
  const issues = useStore((s) => s.issues).filter((i: Issue) => i.iri === iri)
  if (!issues.length) return null
  return (
    <section className="border-t border-line px-4 py-2">
      {issues.map((i) => (
        <p key={i.code + i.message} className={`text-[11.5px] leading-snug ${i.level === 'error' ? 'text-red-700' : 'text-amber-700'}`}>
          {i.level === 'error' ? '오류' : '경고'}: {i.message}
        </p>
      ))}
    </section>
  )
}

function SourceLink({ e }: { e: Entity }) {
  const select = useStore((s) => s.select)
  if (!e.source) return <div className="text-[12px] text-red-700">출처(prov:wasDerivedFrom)가 없습니다</div>
  const { table, column } = e.source
  return (
    <button className={`${link} font-mono text-[12px] text-accent`} onClick={() => select({ kind: 'table', table })} title="ERD에서 이 테이블 보기">
      {column ? `${table}.${column}` : table}
    </button>
  )
}

function TripleTable({ subject, ontology }: { subject: Entity; ontology: Ontology }) {
  return <TripleEditor subject={subject} rows={ontology.triples[subject.iri] ?? []} />
}

function ClassPanel({ iri, ontology, idx }: { iri: string; ontology: Ontology; idx: OntologyIndex }) {
  const select = useStore((s) => s.select)
  const edit = useStore((s) => s.edit)
  const c = idx.classByIri.get(iri)
  if (!c) return null
  const dataProps = idx.dataPropsByClass.get(iri) ?? []
  const out = ontology.object_properties.filter((p) => p.domains.includes(iri))
  const inc = ontology.object_properties.filter((p) => p.ranges.includes(iri))
  const children = ontology.classes.filter((x) => x.parents.includes(iri))
  const name = (x: string) => idx.classByIri.get(x)?.name ?? x
  return (
    <aside className={shell}>
      <Header tone="onto" title={c.label || c.name} subtitle={<span className="font-mono">클래스 · ont:{c.name}</span>} />
      <IssueList iri={c.iri} />
      <Section title="라벨">
        <LabelField e={c} />
      </Section>
      <Section title="설명">
        <Comments e={c} />
      </Section>
      <Section title="출처 테이블">
        <SourceLink e={c} />
      </Section>
      <Section title="상위 클래스">
        <ClassListEditor values={c.parents} classes={ontology.classes} exclude={c.iri} onPick={(p) => select({ kind: 'class', iri: p })} onSave={(v) => edit([{ op: 'set_parents', iri: c.iri, values: v }])} />
        {children.length > 0 && (
          <div className="mt-2">
            <div className="mb-0.5 text-[11px] text-muted">하위 클래스</div>
            {children.map((x) => (
              <button key={x.iri} className={`${link} block font-mono text-[12px]`} onClick={() => select({ kind: 'class', iri: x.iri })}>
                ↓ {x.name}
              </button>
            ))}
          </div>
        )}
      </Section>
      <Section title={`데이터 속성 · ${dataProps.length}`}>
        {dataProps.length === 0
          ? none
          : dataProps.map((p) => (
              <button key={p.iri} className={`${link} flex w-full items-baseline justify-between gap-2`} onClick={() => select({ kind: 'dataprop', iri: p.iri })}>
                <span className="truncate font-mono text-[12px]">{p.name}</span>
                <span className="shrink-0 font-mono text-[10px] text-muted">{p.ranges.join(', ')}</span>
              </button>
            ))}
      </Section>
      <Section title={`객체 속성 (관계) · 나감 ${out.length} · 들어옴 ${inc.length}`}>
        {out.length + inc.length === 0 && none}
        {out.map((p) => (
          <button key={`o${p.iri}`} className={`${link} block w-full font-mono text-[11px]`} onClick={() => select({ kind: 'objprop', iri: p.iri })}>
            {p.name} → {p.ranges.map(name).join(', ')}
          </button>
        ))}
        {inc.map((p) => (
          <button key={`i${p.iri}`} className={`${link} block w-full font-mono text-[11px] text-slate-500`} onClick={() => select({ kind: 'objprop', iri: p.iri })}>
            {p.domains.map(name).join(', ')} → {p.name}
          </button>
        ))}
        <AddRelation domain={c} ontology={ontology} />
      </Section>
      <Section title={`트리플 · ${(ontology.triples[iri] ?? []).length}`}>
        <TripleTable subject={c} ontology={ontology} />
      </Section>
    </aside>
  )
}

function PropertyPanel({ sel, ontology, idx }: { sel: Extract<Selection, { kind: 'objprop' | 'dataprop' }>; ontology: Ontology; idx: OntologyIndex }) {
  const select = useStore((s) => s.select)
  const edit = useStore((s) => s.edit)
  const isObject = sel.kind === 'objprop'
  const p = isObject ? idx.objProp.get(sel.iri) : idx.dataProp.get(sel.iri)
  if (!p) return null
  return (
    <aside className={shell}>
      <Header tone="onto" title={p.label || p.name} subtitle={<span className="font-mono">{isObject ? '객체 속성 (관계)' : '데이터 속성'} · ont:{p.name}</span>} />
      <IssueList iri={p.iri} />
      {isObject && (
        <Section title="이름 (IRI)">
          <NameField e={p} />
        </Section>
      )}
      <Section title="라벨">
        <LabelField e={p} />
      </Section>
      <Section title="도메인">
        <ClassListEditor values={p.domains} classes={ontology.classes} onPick={(iri) => select({ kind: 'class', iri })} onSave={(v) => edit([{ op: 'set_domain', iri: p.iri, values: v }])} />
      </Section>
      <Section title="범위">
        {isObject ? (
          <ClassListEditor values={p.ranges} classes={ontology.classes} onPick={(iri) => select({ kind: 'class', iri })} onSave={(v) => edit([{ op: 'set_range', iri: p.iri, values: v }])} />
        ) : (
          <div className="flex items-center gap-2">
            <select
              aria-label="범위 자료형"
              className="rounded border border-line px-1.5 py-0.5 font-mono text-[12px]"
              value={p.ranges[0] ?? ''}
              onChange={(e) => void edit([{ op: 'set_range', iri: p.iri, values: e.target.value ? [e.target.value] : [] }])}
            >
              <option value="">(없음)</option>
              {[...new Set([...(p.ranges[0] ? [p.ranges[0]] : []), ...XSD_TYPES])].map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
            <span className="text-[11px] text-muted">고르면 바로 적용됩니다</span>
          </div>
        )}
      </Section>
      <Section title="설명">
        <Comments e={p} />
      </Section>
      {!isObject && (
        <Section title="코드값 설명">
          <EditableText
            value={p.value_description}
            multiline
            placeholder="없음 (예: G = 전체 관람가, NC-17 = 성인)"
            hint="컬럼에 담긴 코드값의 의미를 적습니다. 'Value meanings:'로 시작하는 rdfs:comment로 저장되어 에이전트가 설명 검색에서 함께 읽습니다. DB의 실제 값은 바뀌지 않습니다."
            onSave={(v) => edit([{ op: 'set_value_description', iri: p.iri, value: v }])}
          />
        </Section>
      )}
      <Section title={isObject ? '출처 (외래 키 컬럼)' : '출처 컬럼'}>
        <SourceLink e={p} />
      </Section>
      <Section title={`트리플 · ${(ontology.triples[p.iri] ?? []).length}`}>
        <TripleTable subject={p} ontology={ontology} />
      </Section>
      <section className="border-t border-line px-4 py-3">
        <button
          className="rounded-md border border-red-300 px-2.5 py-1 text-[12px] text-red-700 hover:bg-red-50"
          onClick={() => {
            if (window.confirm(`${p.name} 속성을 온톨로지에서 삭제할까요?\n이 속성을 쓰는 제약도 함께 지워집니다. 되돌리기로 복구할 수 있습니다.`)) {
              void edit([{ op: 'delete_property', iri: p.iri }]).then((ok) => ok && select(null))
            }
          }}
        >
          이 속성 삭제
        </button>
      </section>
    </aside>
  )
}

export function RightPanel() {
  const schema = useStore((s) => s.schema)
  const ontology = useStore((s) => s.ontology)
  const selection = useStore((s) => s.selection)
  const gen = useStore((s) => s.gen)
  const idx = useOntologyIndex()
  // "ERD"(DB만) 보기와 온톨로지를 불러오기 전에는 DB 정보만 보여준다
  const withOntology = useStore(showsOntology)
  if (!schema) {
    return (
      <aside className={`${shell} p-4`}>
        <h2 className="mb-2 text-[13px] font-semibold">사용 순서</h2>
        <ol className="list-decimal space-y-2 pl-4 text-[12px] leading-relaxed text-slate-600">
          <li>DB 파일을 불러오면 구조를 읽어 ERD를 그립니다.</li>
          <li>“온톨로지 생성하기”로 그 DB의 온톨로지 파일을 만듭니다.</li>
          <li>만든 파일을 불러오면 클래스와 관계가 그래프로 나타납니다.</li>
          <li>아래 채팅창에서 질문하면 에이전트가 온톨로지를 검색한 뒤 SQL로 답합니다.</li>
        </ol>
      </aside>
    )
  }
  if (gen) return <GenerationPanel gen={gen} />

  const sel = withOntology ? resolveSelection(selection, idx) : selection
  if (sel && ontology && idx && withOntology) {
    if (sel.kind === 'class') return <ClassPanel iri={sel.iri} ontology={ontology} idx={idx} />
    if (sel.kind === 'objprop' || sel.kind === 'dataprop') return <PropertyPanel sel={sel} ontology={ontology} idx={idx} />
  }
  if (sel?.kind === 'table' || sel?.kind === 'column') {
    const table = schema.tables.find((t) => t.name === sel.table)
    if (table) return <TablePanel table={table} schema={schema} idx={withOntology ? idx : null} column={sel.kind === 'column' ? sel.column : undefined} />
  }
  return <Overview schema={schema} ontology={withOntology ? ontology : null} loaded={ontology !== null} />
}

