import { Handle, Position, type Node, type NodeProps } from '@xyflow/react'
import { memo } from 'react'
import { useStore } from '../store'
import type { Table } from '../types'
import { HEADER_HEIGHT, NODE_WIDTH, ROW_HEIGHT } from './layout'

export type TableNodeData = {
  table: Table
  /** 다른 테이블의 외래 키가 가리키는 컬럼 */
  referenced: string[]
  dimmed: boolean
  /** 질의 경로의 지금 단계에서 쓰인 테이블 */
  glow: boolean
  /** 강조할 컬럼 이름 */
  hlColumns: string[]
  /** "ERD + 온톨로지" 보기: 이 테이블에서 나온 클래스 */
  classes: { iri: string; label: string; active: boolean }[]
  /** "ERD + 온톨로지" 보기: 컬럼 이름 → 대응하는 온톨로지 속성 */
  onto: Record<string, OntoColumn>
}

export interface OntoColumn {
  kind: 'objprop' | 'dataprop'
  iri: string
  label: string
}
export type TableNodeType = Node<TableNodeData, 'table'>

/** 컬럼 행의 양쪽 끝에 붙는 연결점 id. 선은 두 테이블의 좌우 위치에 따라 가까운 쪽을 쓴다. */
export const handleId = (kind: 'source' | 'target', side: 'l' | 'r', column: string) => `${kind}:${side}:${column}`

function Badge({ kind }: { kind: 'PK' | 'FK' }) {
  return (
    <span
      className={`inline-flex h-4 w-6 shrink-0 items-center justify-center rounded-[3px] text-[9px] font-bold tracking-wide ${
        kind === 'PK' ? 'bg-amber-100 text-pk' : 'bg-blue-100 text-fk'
      }`}
    >
      {kind}
    </span>
  )
}

function TableNodeImpl({ data, selected }: NodeProps<TableNodeType>) {
  const { table, referenced, dimmed, glow, hlColumns, classes, onto } = data
  const withOntology = classes.length > 0 || Object.keys(onto).length > 0
  const setTip = useStore((s) => s.setTip)
  const select = useStore((s) => s.select)

  return (
    <div className={`relative transition-opacity ${dimmed ? 'opacity-35' : ''}`}>
      <div
        style={{ width: NODE_WIDTH }}
        className={`overflow-hidden rounded-md border bg-white shadow-sm transition-shadow ${selected ? 'border-accent shadow-md ring-2 ring-accent/30' : 'border-line'} ${glow ? 'trace-glow' : ''}`}
      >
        <div style={{ height: HEADER_HEIGHT }} className={`flex items-center justify-between gap-2 px-3 text-white ${selected ? 'bg-accent' : 'bg-slate-700'}`}>
          <span className="truncate font-mono text-[13px] font-semibold">{table.name}</span>
          {withOntology ? (
            <span className="flex min-w-0 shrink gap-1">
              {classes.map((b) => (
                <button
                  key={b.iri}
                  title="대응하는 온톨로지 클래스 (누르면 클래스 정보)"
                  onClick={(e) => {
                    e.stopPropagation()
                    select({ kind: 'class', iri: b.iri })
                  }}
                  className={`nodrag truncate rounded-full px-2 py-0.5 text-[10.5px] font-semibold ${b.active ? 'bg-white text-onto' : 'bg-onto text-white hover:brightness-110'}`}
                >
                  ◆ {b.label}
                </button>
              ))}
            </span>
          ) : (
            <span className="shrink-0 text-[10px] opacity-75">{table.row_count.toLocaleString()}행</span>
          )}
        </div>
        {/* 외래 키가 없는 조인을 그릴 때 쓰는 연결점 (머리 부분) */}
        <Handle className="erd-handle" type="source" position={Position.Left} id="join:source:l" style={{ top: HEADER_HEIGHT / 2 }} isConnectable={false} />
        <Handle className="erd-handle" type="source" position={Position.Right} id="join:source:r" style={{ top: HEADER_HEIGHT / 2 }} isConnectable={false} />
        <Handle className="erd-handle" type="target" position={Position.Left} id="join:target:l" style={{ top: HEADER_HEIGHT / 2 }} isConnectable={false} />
        <Handle className="erd-handle" type="target" position={Position.Right} id="join:target:r" style={{ top: HEADER_HEIGHT / 2 }} isConnectable={false} />
        {table.columns.map((c) => (
          <div
            key={c.name}
            style={{ height: ROW_HEIGHT }}
            className={`relative flex cursor-pointer items-center gap-1.5 border-t border-slate-100 px-2 ${hlColumns.includes(c.name) ? 'bg-amber-100' : 'hover:bg-slate-50'}`}
            onClick={(e) => {
              e.stopPropagation()
              select({ kind: 'column', table: table.name, column: c.name })
            }}
            onMouseEnter={(e) => setTip({ x: e.clientX, y: e.clientY, table: table.name, column: c })}
            onMouseMove={(e) => setTip({ x: e.clientX, y: e.clientY, table: table.name, column: c })}
            onMouseLeave={() => setTip(null)}
          >
            <span className="flex w-[52px] shrink-0 gap-0.5">
              {c.pk && <Badge kind="PK" />}
              {c.fk && <Badge kind="FK" />}
            </span>
            <span className={`min-w-0 flex-1 truncate font-mono text-[12px] ${c.pk ? 'font-semibold' : ''}`}>{c.name}</span>
            {withOntology ? (
              <span className={`max-w-[46%] shrink-0 truncate text-[10.5px] ${onto[c.name] ? 'text-onto' : 'text-slate-300'}`}>
                {onto[c.name] ? `${onto[c.name].kind === 'objprop' ? '→ ' : ''}${onto[c.name].label}` : '—'}
              </span>
            ) : (
              <span className="shrink-0 font-mono text-[10px] text-muted">{c.type}</span>
            )}
            {c.fk && (
              <>
                <Handle className="erd-handle" type="source" position={Position.Left} id={handleId('source', 'l', c.name)} isConnectable={false} />
                <Handle className="erd-handle" type="source" position={Position.Right} id={handleId('source', 'r', c.name)} isConnectable={false} />
              </>
            )}
            {referenced.includes(c.name) && (
              <>
                <Handle className="erd-handle" type="target" position={Position.Left} id={handleId('target', 'l', c.name)} isConnectable={false} />
                <Handle className="erd-handle" type="target" position={Position.Right} id={handleId('target', 'r', c.name)} isConnectable={false} />
              </>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

export const TableNode = memo(TableNodeImpl)
