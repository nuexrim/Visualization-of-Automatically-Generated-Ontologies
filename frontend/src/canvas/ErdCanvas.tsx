import { Background, BackgroundVariant, Controls, MarkerType, MiniMap, ReactFlow, ReactFlowProvider, useNodesState, type BuiltInEdge, type Edge } from '@xyflow/react'
import { useCallback, useMemo, useState } from 'react'
import { columnKey, useOntologyIndex, type OntologyIndex } from '../links'
import { useCanvasHighlight } from '../trace'
import { useTraceCamera } from './useTraceCamera'
import { useStore } from '../store'
import type { Schema } from '../types'
import { HEADER_HEIGHT, NODE_WIDTH, ROW_HEIGHT, nodeHeight, type Positions } from './layout'
import { TableNode, handleId, type OntoColumn, type TableNodeType } from './TableNode'
import { spreadSteps } from './edgeSpread'
import { useCanvasLayout } from './useCanvasLayout'
import { EmptyState } from '../components/EmptyState'

const nodeTypes = { table: TableNode }

/** "ERD + 온톨로지" 보기: 컬럼마다 대응하는 온톨로지 속성의 라벨 */
function ontoColumns(table: string, columns: string[], idx: OntologyIndex): Record<string, OntoColumn> {
  const out: Record<string, OntoColumn> = {}
  for (const c of columns) {
    const hit = idx.propByColumn.get(columnKey(table, c))
    const p = hit && (hit.kind === 'objprop' ? idx.objProp.get(hit.iri) : idx.dataProp.get(hit.iri))
    if (hit && p) out[c] = { kind: hit.kind, iri: hit.iri, label: p.label || p.name }
  }
  return out
}
const ACCENT = '#2f5fd0'
const EDGE = '#94a0b4'
const JOIN = '#d97706'

function Canvas({ schema, withOntology }: { schema: Schema; withOntology: boolean }) {
  const select = useStore((s) => s.select)
  const edgeLabels = useStore((s) => s.edgeLabels)
  const [hovered, setHovered] = useState<string | null>(null)
  const hl = useCanvasHighlight()
  const idx = useOntologyIndex()
  const [nodes, setNodes, onNodesChange] = useNodesState<TableNodeType>([])
  const db = schema.db

  const build = useCallback(
    (positions: Positions): TableNodeType[] => {
      const referenced: Record<string, Set<string>> = {}
      for (const fk of schema.foreign_keys) (referenced[fk.to_table] ??= new Set()).add(fk.to_column)
      return schema.tables.map((t) => ({
        id: t.name,
        type: 'table',
        position: positions[t.name] ?? { x: 0, y: 0 },
        width: NODE_WIDTH,
        height: nodeHeight(t),
        data: { table: t, referenced: [...(referenced[t.name] ?? [])], dimmed: false, glow: false, hlColumns: [], classes: [], onto: {} },
      }))
    },
    [schema],
  )
  const { onNodeDragStop } = useCanvasLayout({
    scope: 'erd',
    db,
    contentKey: db,
    layoutNodes: useMemo(() => schema.tables.map((t) => ({ id: t.name, width: NODE_WIDTH, height: nodeHeight(t) })), [schema]),
    links: useMemo(() => schema.foreign_keys.map((f) => [f.from_table, f.to_table] as [string, string]), [schema]),
    build,
    setNodes,
  })

  // 또렷하게 보일 테이블: 강조된 것 + (테이블 하나를 골랐으면) 그 이웃
  const visible = useMemo(() => {
    if (!hl.active || hl.tables.size === 0) return null
    const set = new Set(hl.tables)
    if (hl.focusTable) {
      for (const fk of schema.foreign_keys) {
        if (fk.from_table === hl.focusTable) set.add(fk.to_table)
        if (fk.to_table === hl.focusTable) set.add(fk.from_table)
      }
    }
    return set
  }, [hl, schema])

  const shownNodes = useMemo(
    () =>
      nodes.map((n) => {
        const t = n.data.table
        return {
          ...n,
          selected: hl.tables.has(n.id),
          data: {
            ...n.data,
            dimmed: visible ? !visible.has(n.id) : false,
            glow: hl.now?.tables.has(n.id) ?? false,
            hlColumns: t.columns.filter((c) => hl.columns.has(columnKey(t.name, c.name))).map((c) => c.name),
            classes: withOntology ? (idx?.classesByTable.get(t.name) ?? []).map((c) => ({ iri: c.iri, label: c.label || c.name, active: hl.classes.has(c.iri) })) : [],
            onto: withOntology && idx ? ontoColumns(t.name, t.columns.map((c) => c.name), idx) : {},
          },
        }
      }),
    [nodes, hl, visible, withOntology, idx],
  )

  // 외래 키마다 선 하나. 두 테이블의 좌우 위치에 따라 가까운 쪽 연결점을 쓴다.
  const edges = useMemo<Edge[]>(() => {
    const centerX = new Map(nodes.map((n) => [n.id, n.position.x + NODE_WIDTH / 2]))
    const pos = new Map(nodes.map((n) => [n.id, n.position]))
    const rowY = (table: string, column: string) => {
      const t = schema.tables.find((x) => x.name === table)
      return (pos.get(table)?.y ?? 0) + HEADER_HEIGHT + Math.max(0, t?.columns.findIndex((c) => c.name === column) ?? 0) * ROW_HEIGHT
    }
    // 세로 구간이 겹치지 않게 선마다 지나갈 길을 나눈다
    const steps = spreadSteps(
      schema.foreign_keys.map((fk) => {
        const sourceOnLeft = (centerX.get(fk.from_table) ?? 0) <= (centerX.get(fk.to_table) ?? 0)
        const sx = (pos.get(fk.from_table)?.x ?? 0) + (sourceOnLeft ? NODE_WIDTH : 0)
        const tx = (pos.get(fk.to_table)?.x ?? 0) + (sourceOnLeft ? 0 : NODE_WIDTH)
        return { id: `${fk.from_table}.${fk.name}`, x1: sx, x2: tx, y: rowY(fk.from_table, fk.from_column) }
      }),
    )
    const fkEdges = schema.foreign_keys.map((fk) => {
      const id = `${fk.from_table}.${fk.name}`
      const sourceOnLeft = (centerX.get(fk.from_table) ?? 0) <= (centerX.get(fk.to_table) ?? 0)
      const isHovered = hovered === id
      const active = hl.columns.has(columnKey(fk.from_table, fk.from_column)) || (hl.focusTable !== null && (hl.focusTable === fk.from_table || hl.focusTable === fk.to_table))
      const faded = visible !== null && !active
      // SQL 단계에서 이 외래 키로 조인했으면 조인 경로 색으로, 지금 단계면 흐르는 애니메이션
      const joined = hl.joins?.some((j) => j.fk?.table === fk.from_table && j.fk.column === fk.from_column) ?? false
      const now = active && (hl.now?.columns.has(columnKey(fk.from_table, fk.from_column)) ?? false)
      const color = joined ? JOIN : active || isHovered ? ACCENT : EDGE
      // 선 이름은 고른 선, 경로에 쓰인 선, 마우스를 올린 선에만 (또는 "선 이름" 켜기)
      const rel = withOntology ? idx?.propByColumn.get(columnKey(fk.from_table, fk.from_column)) : undefined
      const relProp = rel?.kind === 'objprop' ? idx?.objProp.get(rel.iri) : undefined
      const text = relProp ? `◆ ${relProp.label || relProp.name}` : `${fk.from_table}.${fk.from_column} → ${fk.to_table}.${fk.to_column}`
      const showLabel = !faded && (edgeLabels || active || joined || isHovered)
      return {
        id,
        source: fk.from_table,
        target: fk.to_table,
        sourceHandle: handleId('source', sourceOnLeft ? 'r' : 'l', fk.from_column),
        targetHandle: handleId('target', sourceOnLeft ? 'l' : 'r', fk.to_column),
        type: 'smoothstep',
        pathOptions: { stepPosition: steps.get(id) ?? 0.5, borderRadius: 6 },
        data: { table: fk.from_table, column: fk.from_column },
        label: showLabel ? text : undefined,
        labelStyle: { fontSize: 10, fontFamily: relProp ? undefined : 'ui-monospace, Menlo, monospace', fill: joined ? JOIN : relProp ? '#0f766e' : active || isHovered ? ACCENT : '#566074', fontWeight: joined || relProp ? 600 : 400 },
        animated: now,
        labelBgPadding: [4, 2] as [number, number],
        labelBgBorderRadius: 3,
        labelBgStyle: { fill: '#f4f6f9', fillOpacity: 0.92 },
        markerEnd: { type: MarkerType.ArrowClosed, color, width: 16, height: 16 },
        style: { stroke: color, strokeWidth: joined ? 3 : active || isHovered ? 2.25 : 1.25, opacity: faded ? 0.15 : 1, cursor: 'pointer' },
        zIndex: joined ? 20 : active || isHovered ? 10 : 0,
        interactionWidth: 14,
        focusable: false,
      } satisfies BuiltInEdge
    })
    // 외래 키가 없는 조인: 두 테이블 사이에 임시 점선
    const extra: Edge[] = (hl.joins ?? [])
      .filter((j) => !j.fk && centerX.has(j.left_table) && centerX.has(j.right_table))
      .map((j) => {
        const leftFirst = (centerX.get(j.left_table) ?? 0) <= (centerX.get(j.right_table) ?? 0)
        return {
          id: `join:${j.left_table}.${j.left_column}=${j.right_table}.${j.right_column}`,
          source: j.left_table,
          target: j.right_table,
          sourceHandle: `join:source:${leftFirst ? 'r' : 'l'}`,
          targetHandle: `join:target:${leftFirst ? 'l' : 'r'}`,
          type: 'smoothstep',
          label: `${j.left_table}.${j.left_column} = ${j.right_table}.${j.right_column} (${j.via === 'subquery' ? '하위 질의, ' : ''}외래 키 아님)`,
          labelStyle: { fontSize: 10, fontFamily: 'ui-monospace, Menlo, monospace', fill: JOIN, fontWeight: 600 },
          labelBgPadding: [4, 2] as [number, number],
          labelBgBorderRadius: 3,
          labelBgStyle: { fill: '#fff7ed', fillOpacity: 0.95 },
          animated: hl.joinsNow,
          style: { stroke: JOIN, strokeWidth: 2.5, strokeDasharray: '7 5' },
          zIndex: 20,
          selectable: false,
          focusable: false,
        }
      })
    return [...fkEdges, ...extra]
  }, [nodes, schema, hl, visible, hovered, edgeLabels, withOntology, idx])
  const traceIds = useMemo(() => [...(hl.now?.tables ?? [])].filter((t) => nodes.some((n) => n.id === t)), [hl, nodes])
  const onMoveStart = useTraceCamera(traceIds)

  return (
    <ReactFlow
      nodes={shownNodes}
      edges={edges}
      nodeTypes={nodeTypes}
      onNodesChange={onNodesChange}
      onNodeClick={(_, n) => select({ kind: 'table', table: n.id })}
      onEdgeClick={(_, e) => {
        const d = e.data as { table: string; column: string } | undefined
        if (d) select({ kind: 'column', table: d.table, column: d.column })
      }}
      onEdgeMouseEnter={(_, e) => setHovered(e.id)}
      onEdgeMouseLeave={() => setHovered(null)}
      onPaneClick={() => select(null)}
      onNodeDragStop={onNodeDragStop}
      onMoveStart={onMoveStart}
      nodesConnectable={false}
      minZoom={0.03}
      maxZoom={2.5}
      proOptions={{ hideAttribution: true }}
    >
      <Background variant={BackgroundVariant.Dots} gap={24} size={1.2} color="#c9d0dc" />
      <Controls showInteractive={false} position="bottom-left" />
      <MiniMap pannable zoomable position="bottom-right" nodeColor={(n) => (hl.now?.tables.has(n.id) ? JOIN : hl.tables.has(n.id) ? ACCENT : '#64748b')} nodeStrokeWidth={0} maskColor="rgba(244,246,249,0.7)" />
    </ReactFlow>
  )
}

export function ErdCanvas({ withOntology = false }: { withOntology?: boolean }) {
  const schema = useStore((s) => s.schema)
  const loading = useStore((s) => s.loading)
  const error = useStore((s) => s.error)

  if (error) return <div className="flex h-full items-center justify-center p-8 text-center text-red-700">{error}</div>
  if (!schema) return loading ? <div className="flex h-full items-center justify-center text-muted">DB 구조를 읽어 ERD를 만드는 중…</div> : <EmptyState />
  return (
    <ReactFlowProvider key={schema.db}>
      <Canvas schema={schema} withOntology={withOntology} />
    </ReactFlowProvider>
  )
}
