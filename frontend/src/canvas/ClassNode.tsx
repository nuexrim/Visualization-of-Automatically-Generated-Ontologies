import { Handle, Position, type Node, type NodeProps } from '@xyflow/react'
import { memo } from 'react'
import { useStore } from '../store'
import type { DataProperty, OntClass } from '../types'

export const CLASS_WIDTH = 270
const HEADER = 46
const COMMENT = 40
const ROW = 22

export type ClassNodeData = {
  cls: OntClass
  dataProps: DataProperty[]
  /** 이 클래스에서 나가는 객체 속성 수 (연결점을 세로로 나눠 놓는다) */
  outgoing: number
  dimmed: boolean
  /** 질의 경로의 지금 단계에서 찾은 클래스 */
  glow: boolean
  hlProps: string[]
}
export type ClassNodeType = Node<ClassNodeData, 'class'>

/** 화면에 보여줄 설명: 가장 자세한 것 (자동 생성 문구보다 보강된 설명이 길다) */
export const mainComment = (comments: string[]) => comments[comments.length - 1] ?? ''

export const classNodeHeight = (cls: OntClass, nProps: number) => HEADER + (mainComment(cls.comments) ? COMMENT : 0) + nProps * ROW + 2

export const outHandle = (side: 'l' | 'r', i: number) => `out:${side}:${i}`
export const inHandle = (side: 'l' | 'r') => `in:${side}`

/** 데이터 속성 이름에서 테이블 접두어를 뗀다 (film_title → title) */
function shortPropName(p: DataProperty): string {
  const t = p.source?.table
  return t && p.name.toLowerCase().startsWith(`${t.toLowerCase()}_`) ? p.name.slice(t.length + 1) : p.name
}

function ClassNodeImpl({ data, selected }: NodeProps<ClassNodeType>) {
  const { cls, dataProps, outgoing, dimmed, glow, hlProps } = data
  const select = useStore((s) => s.select)
  const comment = mainComment(cls.comments)
  const height = classNodeHeight(cls, dataProps.length)

  return (
    <div
      style={{ width: CLASS_WIDTH }}
      className={`overflow-hidden rounded-xl border bg-white shadow-sm transition-[opacity,box-shadow] ${
        selected ? 'border-onto shadow-md ring-2 ring-onto/30' : cls.external ? 'border-dashed border-slate-400' : 'border-onto/40'
      } ${dimmed ? 'opacity-35' : ''} ${glow ? 'trace-glow trace-glow-onto' : ''}`}
    >
      <div style={{ height: HEADER }} className={`flex flex-col justify-center px-3 ${selected ? 'bg-onto text-white' : 'bg-onto-soft text-ink'}`}>
        <div className="truncate text-[13px] font-semibold">{cls.label || cls.name}</div>
        <div className={`truncate font-mono text-[10px] ${selected ? 'text-white/80' : 'text-muted'}`}>
          ont:{cls.name}
          {cls.source ? ` ← ${cls.source.table}` : cls.external ? ' (외부 상위 클래스)' : ''}
        </div>
      </div>
      {comment && (
        <div style={{ height: COMMENT }} className="border-t border-onto/15 px-3 py-1 text-[10.5px] leading-[15px] text-slate-600" title={comment}>
          <div className="line-clamp-2">{comment}</div>
        </div>
      )}
      {dataProps.map((p) => (
        <div
          key={p.iri}
          style={{ height: ROW }}
          title={`ont:${p.name}${mainComment(p.comments) ? ` — ${mainComment(p.comments)}` : ''}`}
          className={`flex cursor-pointer items-center gap-2 border-t border-slate-100 px-3 ${hlProps.includes(p.iri) ? 'bg-amber-100' : 'hover:bg-slate-50'}`}
          onClick={(e) => {
            e.stopPropagation()
            select({ kind: 'dataprop', iri: p.iri })
          }}
        >
          {/* 라벨이 있으면 라벨(사람이 고친 이름이 바로 보이게), 없으면 테이블 접두어를 뗀 IRI 이름 */}
          {p.label ? <span className="min-w-0 flex-1 truncate text-[11.5px]">{p.label}</span> : <span className="min-w-0 flex-1 truncate font-mono text-[11.5px]">{shortPropName(p)}</span>}
          <span className="shrink-0 font-mono text-[10px] text-muted">{p.ranges[0] ?? ''}</span>
        </div>
      ))}

      {/* 객체 속성: 나가는 선은 옆면에 세로로 나눠 붙이고, 들어오는 선은 머리 부분으로 모은다 */}
      {Array.from({ length: outgoing }, (_, i) => {
        const top = ((i + 1) / (outgoing + 1)) * height
        return (
          <span key={i}>
            <Handle className="erd-handle" type="source" position={Position.Left} id={outHandle('l', i)} style={{ top }} isConnectable={false} />
            <Handle className="erd-handle" type="source" position={Position.Right} id={outHandle('r', i)} style={{ top }} isConnectable={false} />
          </span>
        )
      })}
      <Handle className="erd-handle" type="target" position={Position.Left} id={inHandle('l')} style={{ top: HEADER / 2 }} isConnectable={false} />
      <Handle className="erd-handle" type="target" position={Position.Right} id={inHandle('r')} style={{ top: HEADER / 2 }} isConnectable={false} />
      {/* 상위 클래스 관계: 위로 나가서 상위 클래스의 아래로 들어간다 */}
      <Handle className="erd-handle" type="source" position={Position.Top} id="sub:out" isConnectable={false} />
      <Handle className="erd-handle" type="target" position={Position.Bottom} id="sub:in" isConnectable={false} />
    </div>
  )
}

export const ClassNode = memo(ClassNodeImpl)
